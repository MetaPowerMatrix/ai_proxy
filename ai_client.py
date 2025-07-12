import asyncio
import json
import logging
import os
import datetime
import wave
import uuid
import argparse
import requests
from dotenv import load_dotenv
from pathlib import Path
from pydub import AudioSegment
import random
import websocket
import time
from minicpm_client import MiniCPMClient
import base64
import io


# 加载.env文件中的环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("ai_client")

# 全局变量
AUDIO_DIR = os.getenv("AUDIO_DIR", "audio_files")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "processed_files")
WS_URL = os.getenv("WS_URL", "ws://stream.kalaisai.com:80/ws/proxy")

# 本地服务接口URL
API_URL = "http://127.0.0.1:8000/api/v1"
SPEECH_TO_TEXT_URL = f"{API_URL}/speech-to-text"
MEGATTS_URL = f"http://127.0.0.1:5000/process"
F5TTS_URL = f"http://127.0.0.1:7860/"

QWEN_CHAT_URL = f"{API_URL}/chat/qwen"
UNCENSORED_CHAT_URL = f"{API_URL}/chat/uncensored"

# 状态接口URL
SPEECH_TO_TEXT_STATUS_URL = f"{API_URL}/speech-to-text/status"
MEGATTS_STATUS_URL = f"{API_URL}/megatts/status"
QWEN_CHAT_STATUS_URL = f"{API_URL}/qwen/status"
UNCENSORED_CHAT_STATUS_URL = f"{API_URL}/uncensored/status"

# 会话历史记录
conversation_history = []

# 全局变量
AUDIO_CATEGORIES = {}

# 全局配置变量
USE_MINICPM = False
SKIP_TTS = False
USE_F5TTS = False
USE_UNCENSORED = False

# WebSocket相关配置
WS_HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）- 增加间隔
WS_RECONNECT_DELAY = 3  # 重连延迟（秒）- 减少初始延迟
WS_MAX_RETRIES = 5  # 最大重试次数
WS_CHUNK_SIZE = 4096  # 数据分块大小
WS_SEND_TIMEOUT = 30  # 发送超时时间（秒）
WS_CONNECTION_TIMEOUT = 10  # 连接超时时间（秒）

# 全局变量
ws = None
ws_connected = False
reconnect_attempt = 0
heartbeat_thread = None


def setup_directories():
    """确保必要的目录存在"""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    logger.info(f"已创建目录: {AUDIO_DIR}, {PROCESSED_DIR}")

def on_audio_done(audio_chunks):
    global ws, session_id_bytes
    # 发送音频回复 - 分块发送
    if audio_chunks:
        chunk_size = WS_CHUNK_SIZE
        total_chunks = (len(audio_chunks) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(audio_chunks), chunk_size):
            # 截取一块音频数据
            audio_chunk = audio_chunks[i:i+chunk_size]
            # 发送数据块
            if not send_audio_chunk(ws, session_id_bytes, audio_chunk):
                logger.error(f"发送音频数据块失败: {i//chunk_size + 1}/{total_chunks}")
                break
            # 短暂暂停，避免发送过快
            time.sleep(0.05)


def on_text_done(text_chunks):
    pass


def check_service_status(reference_audio_file):
    global minicpm_client
    """检查本地服务接口的状态"""
    try:
        # 检查MiniCPM服务状态
        if USE_MINICPM:
            minicpm_client = MiniCPMClient()
            response = minicpm_client.check_service_status()
            if response.status_code == 200:
                logger.info(f"MiniCPM服务状态: {response.json()}")
                minicpm_client.init_with_adaptive_vad(reference_audio_file)
                minicpm_client.start_completions_listener(on_audio_done, on_text_done)
            else:
                logger.error(f"MiniCPM服务状态检查失败: {response.status_code}")
                return False

        else:
            # 检查聊天服务状态
            if USE_UNCENSORED:
                response = requests.get(UNCENSORED_CHAT_STATUS_URL)
                if response.status_code == 200:
                    logger.info(f"未审核聊天服务状态: {response.json()}")
                else:
                    logger.error(f"未审核聊天服务状态检查失败: {response.status_code}")
                    return False
            else:
                response = requests.get(QWEN_CHAT_STATUS_URL)
                if response.status_code == 200:
                    logger.info(f"Qwen聊天服务状态: {response.json()}")
                else:
                    logger.error(f"Qwen聊天服务状态检查失败: {response.status_code}")
                    return False

            # 检查语音转文字服务状态
            response = requests.get(SPEECH_TO_TEXT_STATUS_URL)
            if response.status_code == 200:
                logger.info(f"语音转文字服务状态: {response.json()}")
            else:
                logger.error(f"语音转文字服务状态检查失败: {response.status_code}")
                return False

    except Exception as e:
        logger.error(f"服务状态检查失败: {e}")
        return False

    return True

def speech_to_text(audio_path):
    """调用本地服务接口将语音转换为文本"""
    try:
        logger.info(f"开始语音转文字请求: {audio_path}")
        
        # 检查文件是否存在
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None
            
        # 记录文件大小
        file_size = os.path.getsize(audio_path)
        logger.info(f"音频文件大小: {file_size} 字节")
        
        with open(audio_path, 'rb') as audio_file:
            # 为文件指定名称、内容类型和文件对象
            files = {
                'file': (os.path.basename(audio_path), 
                         audio_file, 
                         'audio/wav')  # 指定 MIME 类型为 audio/wav
            }
            
            headers = {
                'Accept': 'application/json'
            }
            
            logger.info(f"发送请求到: {SPEECH_TO_TEXT_URL}")
            logger.info(f"请求头: {headers}")
            logger.info(f"文件名: {os.path.basename(audio_path)}")
            
            response = requests.post(SPEECH_TO_TEXT_URL, files=files, headers=headers)
            
            logger.info(f"收到响应: 状态码={response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                # 根据实际的返回格式解析
                if result.get("code") == 0:
                    transcription = result.get("data", {}).get("transcription", "")
                    language = result.get("data", {}).get("language", "")
                    logger.info(f"语音转文字成功，结果: {transcription}, 语言: {language}")
                    return transcription
                else:
                    logger.error(f"API返回错误: {result.get('message', '未知错误')}")
                    return None
            else:
                logger.error(f"语音转文字失败: 状态码={response.status_code}, 响应内容={response.text}")
                return None
    except Exception as e:
        logger.error(f"语音转文字接口调用失败: {str(e)}")
        import traceback
        logger.error(f"异常堆栈: {traceback.format_exc()}")
        return None

def get_chat_response(prompt):
    """调用聊天接口获取回复，根据配置选择Qwen或Deepseek"""
    global conversation_history
    
    model_name = "Uncensored" if USE_UNCENSORED else "Qwen"
    url = UNCENSORED_CHAT_URL if USE_UNCENSORED else QWEN_CHAT_URL

    try:
        data = {
            "prompt": prompt,
            "history": conversation_history,
            "max_length": 2048,
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        logger.info(f"发送聊天请求到{model_name}，prompt: {prompt[:50]}...")
        response = requests.post(url, json=data)
        
        if response.status_code == 200:
            result = response.json()
            
            # 正确解析API返回格式
            if result.get("code") == 0:
                # 从data.response中获取助手回复
                assistant_response = result.get("data", {}).get("response", "")
                logger.info(f"{model_name}聊天请求成功，回复: {assistant_response[:50]}...")
                return assistant_response
            else:
                logger.error(f"{model_name} API返回错误: {result.get('message', '未知错误')}")
                return None
        else:
            logger.error(f"{model_name}聊天接口调用失败: 状态码={response.status_code}, 响应内容={response.text}")
            return None
    except Exception as e:
        logger.error(f"{model_name}聊天接口调用失败: {str(e)}")
        import traceback
        logger.error(f"异常堆栈: {traceback.format_exc()}")
        return None

def text_to_speech(text, reference_audio_file):
    """调用本地服务接口将文本转换为语音"""
    try:
        logger.info(f"发送文字转语音请求: 文本长度={len(text)}, 参考音频={reference_audio_file}")
        
        data = {
            "wav_path": reference_audio_file,
            "input_text": text,
            "output_dir": "/data/MegaTTS3/output",
        }
        
        response = requests.post(MEGATTS_URL, json=data)
        
        logger.info(f"收到响应: 状态码={response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            output_file = result.get('output_file')
            input_text = result.get('input_text')
            process_time = result.get('process_time')
            
            logger.info(f"文字转语音成功: 输出文件={output_file}, 处理时间={process_time}")
            
            if output_file and os.path.exists(output_file):
                with open(output_file, 'rb') as wav_file:
                    # 读取wav文件，并转换为pcm
                    audio = AudioSegment.from_wav(wav_file)
                    audio_data = audio.raw_data
                    logger.info(f"读取音频文件成功: 大小={len(audio_data)}字节")
                    return audio_data
            else:
                logger.error(f"输出文件不存在或路径无效: {output_file}")
                return None
        else:
            logger.error(f"文字转语音失败: 状态码={response.status_code}, 响应内容={response.text}")
            return None
    except Exception as e:
        logger.error(f"文字转语音接口调用失败: {str(e)}")
        import traceback
        logger.error(f"异常堆栈: {traceback.format_exc()}")
        return None


def use_f5tts(text, reference_audio_file):
    from gradio_client import Client, handle_file

    # 读取reference_audio_file同名的txt文件，如果文件不存在，则使用空字符串
    reference_text_file = reference_audio_file.replace(".wav", ".txt")
    if os.path.exists(reference_text_file):
        with open(reference_text_file, "r", encoding="utf-8") as f:
            reference_text = f.read()
    else:
        reference_text = ""

    client = Client(F5TTS_URL)
    output_audio_path, _, _, _ = client.predict(
            ref_audio_input=handle_file(reference_audio_file),
            ref_text_input=reference_text,
            gen_text_input=text,
            remove_silence=False,
            randomize_seed=True,
            seed_input=random.randint(0, 1000000),
            cross_fade_duration_slider=0.15,
            nfe_slider=32,
            speed_slider=0.8,
            api_name="/basic_tts"
    )
    if output_audio_path and os.path.exists(output_audio_path):
        with open(output_audio_path, 'rb') as wav_file:
            # 读取wav文件，并转换为pcm
            audio = AudioSegment.from_wav(wav_file)
            audio_data = audio.raw_data
            logger.info(f"读取音频文件成功: 大小={len(audio_data)}字节")
            return audio_data
    else:
        logger.error(f"输出文件不存在或路径无效: {output_audio_path}")
        return None


def process_audio(raw_audio_data, session_id):
    """处理音频数据的完整流程，支持选择不同的处理模式"""
    global reference_audio_file
    
    try:
        # 生成唯一文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        wav_file_path = os.path.join(AUDIO_DIR, f"audio_input_{session_id}_{timestamp}.wav")
        
        # 将原始数据保存为WAV文件
        with wave.open(wav_file_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(raw_audio_data)
        logger.info(f"已保存WAV文件: {wav_file_path}")
        
        # MiniCPM模式：直接将音频发送给MiniCPM处理
        if USE_MINICPM:
            global minicpm_client
            logger.info("使用MiniCPM模式处理音频...")
            audio_resp, txt_resp = minicpm_client.test_chunked_audio_processing(wav_file_path)
            return audio_resp, txt_resp

        # 常规模式：语音转文字 -> 聊天 -> 文字转语音
        else:
            logger.info("开始语音识别...")
            transcript = speech_to_text(wav_file_path)
            if not transcript:
                logger.warning("语音识别失败，未能获取文本")
                return None, "抱歉，无法识别您的语音。"
            
            logger.info(f"语音识别结果: {transcript}")
            
            # 获取聊天回复
            logger.info("正在获取AI回复...")
            ai_response = get_chat_response(transcript)
            if not ai_response:
                logger.warning("获取AI回复失败")
                return None, "抱歉，无法获取AI回复。"
            
            logger.info(f"AI回复: {ai_response}")
            
            # 如果需要跳过TTS步骤
            if SKIP_TTS:
                logger.info("跳过TTS步骤，仅返回文本回复")
                return None, ai_response
            
            # 生成语音回复
            logger.info("正在生成语音回复...")
            if USE_F5TTS:
                audio_response = use_f5tts(ai_response, reference_audio_file)
            else:
                audio_response = text_to_speech(ai_response, reference_audio_file)

            # 如果成功生成语音
            if audio_response:
                logger.info(f"已生成语音回复: {len(audio_response)} 字节")
                return audio_response, ai_response
            
            logger.warning("语音合成失败")
            return None, ai_response
            
    except Exception as e:
        logger.error(f"处理音频流程出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, "处理请求时发生错误。"

def send_audio_chunk(ws, session_id_bytes, audio_chunk, retry_count=0):
    """发送音频数据块，带重试机制"""
    global ws_connected
    
    try:
        # 检查连接状态
        if not ws or not hasattr(ws, 'sock') or not ws.sock:
            logger.error("WebSocket对象无效")
            ws_connected = False
            return False
            
        if not ws_connected:
            logger.error("WebSocket连接状态为断开")
            return False
            
        # 添加会话ID前缀
        data_with_session = session_id_bytes + audio_chunk
        ws.send(data_with_session, websocket.ABNF.OPCODE_BINARY)
        logger.debug(f"成功发送音频数据块: {len(audio_chunk)} 字节")
        return True
        
    except websocket.WebSocketConnectionClosedException as e:
        logger.warning(f"WebSocket连接已关闭: {e}")
        ws_connected = False
        
        if retry_count < WS_MAX_RETRIES:
            logger.info(f"等待重连后重试发送 ({retry_count + 1}/{WS_MAX_RETRIES})")
            time.sleep(2)  # 等待重连
            return send_audio_chunk(ws, session_id_bytes, audio_chunk, retry_count + 1)
        else:
            logger.error("达到最大重试次数，发送失败")
            return False
            
    except websocket.WebSocketTimeoutException:
        logger.warning("发送数据超时")
        return False
        
    except Exception as e:
        logger.error(f"发送数据时出错: {str(e)}")
        ws_connected = False
        return False

def on_message(ws, message):
    """处理接收到的消息"""
    try:
        # 判断消息类型 - 文本还是二进制
        if isinstance(message, str):
            pass

        elif isinstance(message, bytes):
            binary_data = message
            
            # 从二进制数据中提取会话ID（前16字节）和音频数据
            if len(binary_data) > 16:
                # 提取会话ID（UUID格式，存储在前16字节）
                global session_id_bytes
                session_id_bytes = binary_data[:16]
                raw_audio = binary_data[16:]
                
                try:
                    # 将字节转换为UUID字符串
                    session_id = uuid.UUID(bytes=session_id_bytes).hex
                    logger.info(f"收到音频数据: 会话ID = {session_id}, 大小 = {len(raw_audio)} 字节")
                    
                    audio_response, text_response = process_audio(raw_audio, session_id)
                    
                    # 发送音频回复 - 分块发送
                    if audio_response:
                        chunk_size = WS_CHUNK_SIZE
                        total_chunks = (len(audio_response) + chunk_size - 1) // chunk_size
                        
                        for i in range(0, len(audio_response), chunk_size):
                            # 截取一块音频数据
                            audio_chunk = audio_response[i:i+chunk_size]
                            # 发送数据块
                            if not send_audio_chunk(ws, session_id_bytes, audio_chunk):
                                logger.error(f"发送音频数据块失败: {i//chunk_size + 1}/{total_chunks}")
                                break
                            logger.info(f"发送音频回复块: 会话ID = {session_id}, 块大小 = {len(audio_chunk)} 字节, 进度: {i//chunk_size + 1}/{total_chunks}")
                            # 短暂暂停，避免发送过快
                            time.sleep(0.05)
                    
                    logger.info(f"会话 {session_id} 处理完成")
                    
                except ValueError:
                    logger.error("无法解析会话ID")
            else:
                logger.error(f"收到无效的音频数据: 长度过短 ({len(binary_data)} 字节)")
    
    except Exception as e:
        import sys
        exc_type, exc_obj, exc_tb = sys.exc_info()
        line_number = exc_tb.tb_lineno
        logger.error(f"处理消息时出错: {str(e)}, 出错行号: {line_number}")

def start_websocket():
    """启动WebSocket连接"""
    global ws, ws_connected, heartbeat_thread
    
    try:
        logger.info(f"正在连接到WebSocket: {WS_URL}")
        
        ws = websocket.WebSocketApp(
            WS_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
            on_ping=on_ping,
            on_pong=on_pong
        )
        
        # 启动心跳线程
        if heartbeat_thread is None or not heartbeat_thread.is_alive():
            heartbeat_thread = start_heartbeat()
        
        # 设置WebSocket选项，包括超时配置
        ws.run_forever(
            ping_interval=60,  # 每60秒发送ping
            ping_timeout=10,   # ping超时时间
            sslopt={"check_hostname": False, "cert_reqs": websocket.ssl.CERT_NONE} if WS_URL.startswith('wss') else None
        )
        
    except Exception as e:
        logger.error(f"WebSocket启动失败: {e}")
        ws_connected = False
        
    finally:
        # 确保心跳线程正确关闭
        if heartbeat_thread and heartbeat_thread.is_alive():
            logger.info("等待心跳线程结束...")
            heartbeat_thread.join(timeout=5)
            
def initialize_audio_categories():
    """初始化音频分类"""
    global AUDIO_CATEGORIES
    voice_cat_file = Path("voice_cat.json")
    
    if voice_cat_file.exists():
        # 如果voice_cat.json文件存在，直接加载分类信息
        with open(voice_cat_file, "r", encoding="utf-8") as f:
            AUDIO_CATEGORIES = json.load(f)
        logger.info("已从voice_cat.json加载音频分类信息")
    else:
        # 如果voice_cat.json文件不存在，读取音频文件并生成分类信息
        assets_dir = Path("/data/MegaTTS3/assets")
        male_dir = assets_dir / "男"
        female_dir = assets_dir / "女"
        
        AUDIO_CATEGORIES = {}
        
        # 处理"男"目录下的音频文件
        if male_dir.exists() and male_dir.is_dir():
            for file_path in male_dir.glob("*.wav"):
                file_name = file_path.stem  # 获取文件名（不含扩展名）
                AUDIO_CATEGORIES[file_name] = str(file_path)
        
        # 处理"女"目录下的音频文件
        if female_dir.exists() and female_dir.is_dir():
            for file_path in female_dir.glob("*.wav"):
                file_name = file_path.stem  # 获取文件名（不含扩展名）
                AUDIO_CATEGORIES[file_name] = str(file_path)
        
        # 将分类信息保存到voice_cat.json文件
        with open(voice_cat_file, "w", encoding="utf-8") as f:
            json.dump(AUDIO_CATEGORIES, f, ensure_ascii=False, indent=4)
        logger.info("已生成并保存音频分类信息到voice_cat.json")

def main():
    # 参数解析
    parser = argparse.ArgumentParser(description="AI音频处理客户端")
    parser.add_argument("--use-minicpm", action="store_true", 
                      help="使用MiniCPM大模型进行语音处理")
    parser.add_argument("--skip-tts", action="store_true", 
                      help="跳过文本转语音步骤")
    parser.add_argument("--use-f5tts", action="store_true", 
                      help="使用f5tts接口进行语音处理")
    parser.add_argument("--use-uncensored", action="store_true", 
                      help="使用不审查聊天接口")
    parser.add_argument("--voice-category", type=str, default="御姐配音暧昧",
                      help="指定音色名称，默认为'御姐配音暧昧'")
    
    args = parser.parse_args()
    
    # 设置全局配置
    global USE_MINICPM, SKIP_TTS, USE_F5TTS, AUDIO_DIR, PROCESSED_DIR, USE_UNCENSORED
    USE_MINICPM = args.use_minicpm
    SKIP_TTS = args.skip_tts
    USE_F5TTS = args.use_f5tts
    USE_UNCENSORED = args.use_uncensored

    # 创建必要的目录
    setup_directories()
    
    # 初始化音频分类
    initialize_audio_categories()
        
    # 设置音色名称
    global reference_audio_file
    reference_audio_file = AUDIO_CATEGORIES.get(args.voice_category, AUDIO_CATEGORIES["御姐配音暧昧"])

    # 检查服务状态
    if not check_service_status(reference_audio_file):
        logger.error("服务状态检查失败，请检查服务是否正常运行")
        return

    # 打印启动信息
    logger.info("=" * 50)
    logger.info("AI音频处理客户端启动")
    logger.info(f"WebSocket URL: {WS_URL}")
    logger.info(f"音频文件目录: {AUDIO_DIR}")
    logger.info(f"处理文件目录: {PROCESSED_DIR}")
    logger.info(f"使用MiniCPM: {USE_MINICPM}")
    logger.info(f"使用f5tts: {USE_F5TTS}")
    logger.info(f"使用不审查聊天接口: {USE_UNCENSORED}")
    logger.info(f"跳过TTS: {SKIP_TTS}")
    logger.info(f"音色名称: {args.voice_category}")
    logger.info("=" * 50)
    
    # 启动WebSocket连接
    try:
        start_websocket()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭客户端...")
        # 清理资源
        global ws, ws_connected, heartbeat_thread
        ws_connected = False
        if ws:
            try:
                ws.close()
            except:
                pass
        if heartbeat_thread and heartbeat_thread.is_alive():
            logger.info("等待心跳线程结束...")
            heartbeat_thread.join(timeout=5)
        logger.info("客户端已关闭")
    except Exception as e:
        logger.error(f"客户端运行出错: {e}")
        import traceback
        logger.error(traceback.format_exc())

def send_heartbeat():
    """发送心跳包保持连接活跃"""
    global ws, ws_connected
    
    try:
        if ws and ws_connected and hasattr(ws, 'sock') and ws.sock:
            heartbeat_data = {
                "type": "heartbeat",
                "timestamp": int(time.time()),
                "client_type": "ai_backend"
            }
            ws.send(json.dumps(heartbeat_data))
            logger.debug("已发送心跳包")
            return True
        else:
            logger.debug("WebSocket未连接，跳过心跳")
            return False
    except websocket.WebSocketConnectionClosedException:
        logger.warning("心跳发送失败：连接已关闭")
        ws_connected = False
        return False
    except Exception as e:
        logger.error(f"发送心跳包失败: {str(e)}")
        return False

def start_heartbeat():
    """启动心跳线程"""
    def heartbeat_worker():
        logger.info(f"心跳线程启动，间隔: {WS_HEARTBEAT_INTERVAL}秒")
        
        while True:
            try:
                if not send_heartbeat():
                    # 如果心跳发送失败，等待一段时间后继续尝试
                    time.sleep(5)
                else:
                    time.sleep(WS_HEARTBEAT_INTERVAL)
                    
            except Exception as e:
                logger.error(f"心跳线程出错: {str(e)}")
                time.sleep(10)  # 出错后等待10秒再继续
    
    import threading
    heartbeat = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat.start()
    return heartbeat

# 重连参数
MAX_RECONNECT_ATTEMPTS = 15
INITIAL_RECONNECT_DELAY = 3

def on_error(ws, error):
    """处理错误"""
    global ws_connected
    logger.error(f"WebSocket错误: {error}")
    ws_connected = False

def on_close(ws, close_status_code, close_msg):
    """处理连接关闭"""
    global reconnect_attempt, ws_connected
    
    ws_connected = False
    
    # 分析关闭原因
    close_reason = get_close_reason(close_status_code)
    logger.warning(f"WebSocket连接已关闭: 状态码={close_status_code}, 原因={close_reason}, 消息={close_msg}")
    
    # 决定是否重连
    should_reconnect = should_attempt_reconnect(close_status_code)
    
    if should_reconnect and reconnect_attempt < MAX_RECONNECT_ATTEMPTS:
        reconnect_attempt += 1
        
        # 计算重连延迟（指数退避，最大60秒）
        delay = min(60, INITIAL_RECONNECT_DELAY * (2 ** (reconnect_attempt - 1)))
        
        logger.info(f"第 {reconnect_attempt}/{MAX_RECONNECT_ATTEMPTS} 次重连，将在 {delay} 秒后尝试...")
        time.sleep(delay)
        
        # 重新启动WebSocket
        import threading
        reconnect_thread = threading.Thread(target=start_websocket, daemon=True)
        reconnect_thread.start()
    else:
        if not should_reconnect:
            logger.info("服务端主动关闭连接，不进行重连")
        else:
            logger.error(f"达到最大重连次数 ({MAX_RECONNECT_ATTEMPTS})，停止重连")

def should_attempt_reconnect(close_code):
    """根据关闭代码决定是否应该重连"""
    # 1000: 正常关闭，可以重连
    # 1001: 端点离开，可以重连
    # 1006: 异常关闭，可以重连
    # 1011: 服务器错误，可以重连
    # 其他代码：根据具体情况决定
    reconnectable_codes = [1000, 1001, 1006, 1011]
    return close_code in reconnectable_codes or close_code is None

def get_close_reason(close_code):
    """获取关闭原因的描述"""
    reasons = {
        1000: "正常关闭",
        1001: "端点离开",
        1002: "协议错误",
        1003: "不支持的数据类型",
        1006: "异常关闭",
        1007: "数据格式错误",
        1008: "策略违反",
        1009: "消息过大",
        1010: "扩展协商失败",
        1011: "服务器错误"
    }
    return reasons.get(close_code, f"未知错误码: {close_code}")

def on_open(ws):
    """处理连接成功"""
    global reconnect_attempt, ws_connected
    
    reconnect_attempt = 0
    ws_connected = True
    
    # 发送AI后端标识
    try:
        identification = {
            "client_type": "ai_backend",
            "timestamp": int(time.time()),
            "version": "1.0"
        }
        ws.send(json.dumps(identification))
        logger.info("WebSocket连接已建立，已发送身份标识")
    except Exception as e:
        logger.error(f"发送身份标识失败: {e}")
        ws_connected = False

def on_ping(wsapp, message):
    """处理ping消息"""
    logger.debug("收到ping消息，自动回复pong")

def on_pong(wsapp, message):
    """处理pong消息"""
    logger.debug("收到pong消息")

def get_connection_status():
    """获取连接状态信息"""
    global ws, ws_connected, reconnect_attempt
    
    status = {
        "connected": ws_connected,
        "ws_object": ws is not None,
        "reconnect_attempts": reconnect_attempt,
        "heartbeat_active": heartbeat_thread is not None and heartbeat_thread.is_alive()
    }
    
    if ws and hasattr(ws, 'sock') and ws.sock:
        try:
            status["socket_state"] = "connected" if ws.sock.connected else "disconnected"
        except:
            status["socket_state"] = "unknown"
    else:
        status["socket_state"] = "no_socket"
    
    return status

def log_connection_status():
    """记录连接状态"""
    status = get_connection_status()
    logger.info(f"连接状态: {status}")


if __name__ == "__main__":
    main()