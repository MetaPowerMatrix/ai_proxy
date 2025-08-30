#!/bin/bash

# 服务器地址
SERVER="http://172.28.98.201:5001"

# 要上传的文件
FILE_PATH="$1"
if [ -z "$FILE_PATH" ]; then
    echo "请提供要上传的文件路径"
    echo "用法: ./upload_example.sh <文件路径>"
    exit 1
fi

FILENAME=$(basename "$FILE_PATH")
CHUNK_SIZE=$((5 * 1024 * 1024))  # 5MB per chunk

# 计算总分片数
TOTAL_CHUNKS=$(( ($(stat -f%z "$FILE_PATH") + CHUNK_SIZE - 1) / CHUNK_SIZE ))

echo "开始上传文件: $FILENAME"
echo "总分片数: $TOTAL_CHUNKS"

# 分片上传
for ((i=0; i<TOTAL_CHUNKS; i++)); do
    echo "正在上传分片 $i / $TOTAL_CHUNKS"
    
    # 使用dd命令切分文件并通过curl上传
    dd if="$FILE_PATH" bs=$CHUNK_SIZE skip=$i count=1 2>/dev/null | \
    curl -X POST "${SERVER}/upload/chunk" \
        -F "file=@-" \
        -F "chunk=$i" \
        -F "total_chunks=$TOTAL_CHUNKS" \
        -F "filename=$FILENAME" \
        -H "Content-Type: multipart/form-data"
    
    echo ""
done

# 检查上传状态
echo "检查上传状态..."
curl "${SERVER}/upload/status/$FILENAME"

# 计算文件MD5并验证
MD5=$(md5 -q "$FILE_PATH")
echo "验证文件完整性..."
curl -X POST "${SERVER}/upload/verify" \
    -H "Content-Type: application/json" \
    -d "{\"filename\": \"$FILENAME\", \"hash\": \"$MD5\"}"

echo "上传完成！"
