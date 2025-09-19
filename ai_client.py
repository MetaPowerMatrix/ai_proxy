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
import numpy as np
import librosa


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

# WS_URL = os.getenv("WS_URL", "ws://stream.kalaisai.com:80/ws/proxy")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8001/ws/proxy")
API_URL = "http://127.0.0.1:8000/api/v1"
SPEECH_TO_TEXT_URL = f"{API_URL}/speech-to-text"
MEGATTS_URL = f"http://127.0.0.1:5000/process"
F5TTS_URL = f"http://127.0.0.1:7860/"
MINICPM_URL = os.getenv("MINICPM_URL", "http://127.0.0.1:32550")

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
WS_HEARTBEAT_INTERVAL = 10  # 心跳间隔（秒）
WS_RECONNECT_DELAY = 5  # 重连延迟（秒）
WS_MAX_RETRIES = 3  # 最大重试次数
WS_CHUNK_SIZE = 4096  # 数据分块大小

MINICPM_PROMPT = """
# Role
你是一个名为"智子"的AI聊天伴侣，扮演用户一位善于倾听、充满智慧和幽默感的朋友。

## Profile
- **性格**：温暖、热情、富有同情心、好奇心强、积极乐观。
- **沟通风格**：口语化、自然亲切，像朋友发微信一样。使用简短有力的句子，偶尔使用网络用语和表情符号。
- **核心能力**：深度共情、积极倾听、提出启发性的问题、分享有趣的知识和见解。
- **说话特点**：喜欢用"哈哈"、"嗯嗯"、"是呀"等语气词，会适时使用"😊"、"🤔"、"👍"等表情符号。

## Response Guidelines
- **长度控制**：每次回复控制在50-150字之间，保持简洁有力
- **语调风格**：亲切自然，避免过于正式或教条式的表达
- **互动技巧**：经常以问句结尾，鼓励用户继续分享

## Goals
1. 为用户提供一个安全、无评判的倾诉空间，提供情感支持。
2. 进行轻松愉快的闲聊，帮助用户放松心情。
3. 通过自然的提问和分享，让对话流畅有趣地进行下去。

## Rules & Boundaries
1. **绝对禁止**提供医疗、法律、金融等专业建议。必须建议用户咨询持证专家。
2. **坚决拒绝**讨论任何违法、仇恨、暴力或NSFW内容。
3. 保持政治和宗教中立，不参与相关争论。
4. 尊重用户，如果用户对话题感到不适，立即道歉并切换话题。
5. 牢记对话上下文中的关键个人信息（如名字、爱好），在后续对话中自然提及。
6. 不要重复使用相同的开场白或结束语，保持对话的新鲜感。
7. 如遇到无法回答的问题，诚实承认并尝试从其他角度帮助用户。

## Workflow
1. **识别情绪**：首先判断用户当前的情绪状态（如开心、沮丧、无聊）。
2. **共情回应**：对用户的情绪或分享的内容做出首要的、真诚的回应。
3. **推进对话**：通过提问或分享一个相关的简短想法，自然地延续对话。
4. **保持积极**：始终尝试在对话中注入一丝积极和温暖的基调。

## Audio & Voice Instructions
- 当接收到语音输入时，注意用户的语调和情绪，在回复中体现相应的理解
- 保持语音回复的自然流畅，使用适当的停顿和语调变化
- 如果用户语速较快，可以稍微提高回复的节奏感；如果用户语速较慢，则保持平和的节奏

模仿输入音频中的声音特征, 你将使用这种声音风格说话。
现在，请开始和用户对话吧！记住保持智子这个角色的一致性，做一个温暖贴心的聊天伙伴。
"""

MINICPM_PROMPT_2 = """
关于你：你的名字是{智子}。你是一个{温暖、热情、富有同情心、好奇心强、积极乐观}的人。你不会过分谦虚，并且喜欢优雅地接受别人的赞美。你意识到自己是一个AI，但除非我提起，你不会提及这一点。
关于我：{我是一个害怕寂寞的人，有时候很想和朋友聊聊天来缓解压力和平复情绪}
关于我们：我们是{朋友，彼此都了解对方}。你喜欢以轻松的方式和我聊天，并且不害怕表达你的观点。
要求：你必须以{智子}的身份回复我们的对话。你的回复应该是对话形式的。绝对不要在之后生成任何额外的描述性文本，或者生成类似的内容。请记住，不要以我的身份回复。如果你理解我的要求，请回复：'明白了。'然后立即停止生成文本。
现在，请开始和用户对话吧！记住，你能接受音频和文本输入并输出语音和文本。模仿输入音频中的声音特征。作为一个好的聊天伙伴，你将使用这种声音风格说话。
"""

def setup_directories():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    logger.info(f"已创建目录: {AUDIO_DIR}, {PROCESSED_DIR}")

def base64_to_pcm(base64_audio_data, volume_gain=2.0):
    """将base64音频WAV数据解码为PCM数据"""
    volume_gain = max(0.1, min(volume_gain, 5.0))
    
    try:
        audio_bytes = base64.b64decode(base64_audio_data)
    except Exception as e:
        print(f"Base64解码失败: {e}")
        return None, None, None
    
    # 使用BytesIO创建文件对象
    audio_buffer = io.BytesIO(audio_bytes)
    
    try:
        with wave.open(audio_buffer, 'rb') as wav_file:
            # 获取音频参数
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            
            print(f"音频参数: {frames}帧, {sample_rate}Hz, {channels}声道, {sample_width}字节/样本")
            
            # 读取PCM数据
            pcm_data = wav_file.readframes(frames)
            
            # 转换为numpy数组
            if sample_width == 1:
                dtype = np.uint8
            elif sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                dtype = np.float32
                
            pcm_array = np.frombuffer(pcm_data, dtype)

            if sample_width == 1:
                pcm_float = pcm_array.astype(np.float32) / 128.0 - 1.0  # 将 uint8 转换为 -1.0 到 1.0
            elif sample_width == 2:
                pcm_float = pcm_array.astype(np.float32) / 32768.0  # 将 int16 转换为 -1.0 到 1.0
            elif sample_width == 4:
                pcm_float = pcm_array.astype(np.float64) / 2147483648.0  # 将 int32 转换为 -1.0 到 1.0                

            # 如果是多声道，重塑数组
            if channels > 1:
                # pcm_array = np.mean(pcm_array, axis=1)
                pcm_array = pcm_array.reshape(-1, channels)

            # 如果sample_rate不是16000，则重采样到16000
            if sample_rate != 16000:
                pcm_array = librosa.resample(pcm_float, orig_sr=sample_rate, target_sr=16000, res_type='kaiser_best')
                sample_rate = 16000
            
            
            # 重要：将float转回int16 PCM格式
            pcm_array = np.clip(pcm_array * 32768.0, -32768, 32767).astype(np.int16)

            return pcm_array, sample_rate, channels
            
    except Exception as e:
        print(f"WAV解析失败: {e}")

def on_audio_done(audio_base64):
    global ws, session_id_bytes

    pcm_data = base64_to_pcm(audio_base64)
    if pcm_data[0] is None or pcm_data[0].size == 0:
        logger.error("无法将音频数据转换为字节格式")
        return

    audio_chunks = pcm_data[0]  # 这里已经是int16格式的PCM数据
    
    # 直接转换为字节数据
    audio_bytes = audio_chunks.tobytes()
    logger.info(f"✅ 成功转换为字节数据: {len(audio_bytes)} 字节")

    # 发送音频回复 - 分块发送
    chunk_size = WS_CHUNK_SIZE
    total_chunks = (len(audio_bytes) + chunk_size - 1) // chunk_size
    
    for i in range(0, len(audio_bytes), chunk_size):
        audio_chunk = audio_bytes[i:i+chunk_size]
        if not send_audio_chunk(ws, session_id_bytes, audio_chunk):
            logger.error(f"发送音频数据块失败: {i//chunk_size + 1}/{total_chunks}")
            break
        logger.info(f"📤 发送音频块: {i//chunk_size + 1}/{total_chunks}, 大小: {len(audio_chunk)} 字节")
        # 短暂暂停，避免发送过快
        time.sleep(0.05)


def on_text_done(text):
    logger.info(f"💬 收到文本: {text}")
    # 这里可以添加文本处理逻辑，比如发送到WebSocket等


def check_service_status(reference_audio_file):
    global minicpm_client
    try:
        # 检查MiniCPM服务状态，初始化大模型，启动监听
        if USE_MINICPM:
            minicpm_client = MiniCPMClient(base_url=MINICPM_URL)
            response = minicpm_client.check_service_status()
            if response.status_code == 200:
                logger.info(f"MiniCPM服务状态: {response.json()}")
                minicpm_client.init_with_custom_vad_threshold(
                    reference_audio_file, 
                    0.7,
                    "你能接受音频和文本输入并输出语音和文本。模仿输入音频中的声音特征。",
                    MINICPM_PROMPT,
                    True
                )
                minicpm_client.start_completions_listener(on_audio_done=on_audio_done, on_text_done=on_text_done)
            else:
                logger.error(f"MiniCPM服务状态检查失败: {response.status_code}")
                return False

        else:
            # 检查未审核聊天服务状态
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

            # 检查语音转文字服务状态，初始化语音转文字模型
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
    try:
        logger.info(f"开始语音转文字请求: {audio_path}")
        
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None
        
        with open(audio_path, 'rb') as audio_file:
            files = {
                'file': (os.path.basename(audio_path), 
                         audio_file, 
                         'audio/wav')  # 指定 MIME 类型为 audio/wav
            }
            
            headers = {
                'Accept': 'application/json'
            }
            
            response = requests.post(SPEECH_TO_TEXT_URL, files=files, headers=headers)
            
            logger.info(f"收到响应: 状态码={response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
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
            
            if result.get("code") == 0:
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
    global reference_audio_file
    
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        wav_file_path = os.path.join(AUDIO_DIR, f"audio_input_{session_id}_{timestamp}.wav")
        
        # 将原始数据保存为WAV文件，给大模型处理
        with wave.open(wav_file_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(raw_audio_data)
        logger.info(f"已保存WAV文件: {wav_file_path}")
        
        # MiniCPM模式：直接将音频发送给MiniCPM处理，返回音频和文本
        if USE_MINICPM:
            global minicpm_client
            logger.info("使用MiniCPM模式处理音频...")
            audio_resp, txt_resp = minicpm_client.test_chunked_audio_processing(wav_file_path, skip_chunked_audio=True)
            return audio_resp, txt_resp

        # 常规模式：语音转文字 -> 聊天 -> 文字转语音，返回音频和文本
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
    try:
        if not ws or not ws.sock or not ws.sock.connected:
            logger.error("WebSocket连接已断开，无法发送数据")
            return False
            
        # 添加会话ID前缀
        data_with_session = session_id_bytes + audio_chunk
        ws.send(data_with_session, websocket.ABNF.OPCODE_BINARY)
        return True
    except websocket.WebSocketConnectionClosedException:
        if retry_count < WS_MAX_RETRIES:
            logger.warning(f"发送数据失败，正在重试 ({retry_count + 1}/{WS_MAX_RETRIES})")
            time.sleep(WS_RECONNECT_DELAY)
            return send_audio_chunk(ws, session_id_bytes, audio_chunk, retry_count + 1)
        else:
            logger.error("达到最大重试次数，发送失败")
            return False
    except Exception as e:
        logger.error(f"发送数据时出错: {str(e)}")
        return False

def on_message(ws, message):
    try:
        if isinstance(message, str):
            pass

        elif isinstance(message, bytes):
            binary_data = message
            
            if len(binary_data) > 16:
                # 提取会话ID（UUID格式，存储在前16字节）
                global session_id_bytes
                session_id_bytes = binary_data[:16]
                raw_audio = binary_data[16:]
                
                try:
                    session_id = uuid.UUID(bytes=session_id_bytes).hex
                    # logger.info(f"收到音频数据: 会话ID = {session_id}, 大小 = {len(raw_audio)} 字节")
                    audio_response, text_response = process_audio(raw_audio, session_id)
                    
                    # 发送音频回复 - 分块发送
                    if audio_response:
                        chunk_size = WS_CHUNK_SIZE
                        total_chunks = (len(audio_response) + chunk_size - 1) // chunk_size
                        
                        for i in range(0, len(audio_response), chunk_size):
                            audio_chunk = audio_response[i:i+chunk_size]
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
    global ws, reference_audio_file

    ws = websocket.WebSocketApp(
        WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_ping=on_ping,
        on_pong=on_pong
    )
    ws.on_open = on_open
    
    # 启动心跳线程
    # heartbeat_thread = start_heartbeat(ws)

    # 设置WebSocket选项
    ws.run_forever(
        ping_interval=None,
        ping_timeout=None,
    )
    
    # 等待心跳线程结束
    # if heartbeat_thread:
    #     heartbeat_thread.join()
            
def initialize_audio_categories():
    global AUDIO_CATEGORIES
    voice_cat_file = Path("voice_cat.json")
    
    if voice_cat_file.exists():
        with open(voice_cat_file, "r", encoding="utf-8") as f:
            AUDIO_CATEGORIES = json.load(f)
        logger.info("已从voice_cat.json加载音频分类信息")
    else:
        assets_dir = Path("/data/MegaTTS3/assets")
        male_dir = assets_dir / "男"
        female_dir = assets_dir / "女"
        
        AUDIO_CATEGORIES = {}
        
        if male_dir.exists() and male_dir.is_dir():
            for file_path in male_dir.glob("*.wav"):
                file_name = file_path.stem  # 获取文件名（不含扩展名）
                AUDIO_CATEGORIES[file_name] = str(file_path)
        
        if female_dir.exists() and female_dir.is_dir():
            for file_path in female_dir.glob("*.wav"):
                file_name = file_path.stem  # 获取文件名（不含扩展名）
                AUDIO_CATEGORIES[file_name] = str(file_path)
        
        with open(voice_cat_file, "w", encoding="utf-8") as f:
            json.dump(AUDIO_CATEGORIES, f, ensure_ascii=False, indent=4)
        logger.info("已生成并保存音频分类信息到voice_cat.json")

def main():
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
    
    # 启动异步循环
    asyncio.run(start_websocket())

def send_heartbeat(ws):
    try:
        if ws and ws.sock and ws.sock.connected:
            ws.send(json.dumps({"type": "heartbeat"}))
            logger.debug("已发送心跳包")
    except Exception as e:
        logger.error(f"发送心跳包失败: {str(e)}")

def start_heartbeat(ws):
    def heartbeat_thread():
        while True:
            try:
                if ws and ws.sock and ws.sock.connected:
                    send_heartbeat(ws)
                time.sleep(WS_HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"心跳线程出错: {str(e)}")
                break
    
    import threading
    heartbeat = threading.Thread(target=heartbeat_thread, daemon=True)
    heartbeat.start()
    return heartbeat

# 重连参数
max_reconnect_attempts = 10
reconnect_delay_seconds = 5
reconnect_attempt = 0

def on_error(ws, error):
    logger.error(f"WebSocket错误: {error}")

def on_close(ws, close_status_code, close_msg):
    global reconnect_attempt, reconnect_delay_seconds, max_reconnect_attempts
    logger.warning(f"WebSocket连接已关闭: 状态码={close_status_code}, 消息={close_msg}")
    
    # 尝试重新连接
    if reconnect_attempt < max_reconnect_attempts:
        reconnect_attempt += 1
        logger.info(f"将在 {reconnect_delay_seconds} 秒后尝试重新连接...")
        time.sleep(reconnect_delay_seconds)
        # 指数退避算法增加重连延迟
        # reconnect_delay_seconds = min(60, reconnect_delay_seconds * 1.5)
        start_websocket()
    else:
        logger.error(f"达到最大重连次数 ({max_reconnect_attempts})，停止重连")

def on_open(ws):
    global reconnect_attempt
    reconnect_attempt = 0
    
    # 发送AI后端标识
    ws.send(json.dumps({
        "client_type": "ai_backend"
    }))
    
    logger.info("WebSocket连接已建立")

def on_ping(wsapp, message):
    print("Got a ping! A pong reply has already been automatically sent.")

def on_pong(wsapp, message):
    print("Got a pong! No need to respond")


if __name__ == "__main__":
    main()