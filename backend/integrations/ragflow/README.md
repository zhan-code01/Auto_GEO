# RAGFlow与geo项目集成框架

本项目提供了一个完整的集成框架，用于在geo项目中调用RAGFlow知识库，实现知识检索和问答功能。

## 项目结构

```
ragflow-geo-integration/
├── ragflow_integration.py     # RAGFlow集成核心代码
├── requirements.txt           # 项目依赖
├── config.json               # 配置文件
├── config_example.json        # 配置文件示例
├── test_integration.py        # 单元测试脚本
├── test_connection.py         # 连接测试脚本
├── check_status.py           # 服务状态检查脚本
├── TESTING.md                # 测试说明文档
└── README.md                 # 本帮助文档
```

## 功能特性

- 与RAGFlow知识库进行交互
- 在知识库中搜索地理空间相关信息
- 上传文档到RAGFlow知识库
- 获取知识库信息和状态

## 环境要求

- Python 3.7+
- RAGFlow服务已部署并运行

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

在使用本集成框架前，您需要准备以下信息：

1. **RAGFlow服务地址**：您部署的RAGFlow服务的URL（如 `http://localhost:9380`）
2. **API密钥**：在RAGFlow控制台获取的API密钥
3. **知识库ID**：您在RAGFlow中创建的知识库的ID

### 获取API密钥

1. 登录RAGFlow界面
2. 点击右上角用户头像
3. 选择"API" → "RAGFlow API"
4. 复制API Key

### 获取知识库ID

1. 在RAGFlow知识库页面
2. 点击特定知识库
3. 浏览器地址栏URL中的ID部分即为知识库ID

## 测试集成框架

本项目包含完整的测试脚本，用于验证集成框架是否正常工作：

### 1. 单元测试
验证代码逻辑和功能：
```bash
python test_integration.py
```

### 2. 服务状态检查
检查RAGFlow服务是否运行及API密钥是否有效：
```bash
python check_status.py
```

### 3. 连接测试
测试与实际RAGFlow服务的连接：
```bash
python test_connection.py
```

## 使用方法

### 1. 基础使用

```python
from ragflow_integration import GeoRAGFlowIntegration

# 配置RAGFlow连接参数
ragflow_config = {
    'base_url': 'http://your-ragflow-host:port',  # 您的RAGFlow服务地址
    'api_key': 'your_api_key',                     # 您的API密钥
    'dataset_id': 'your_dataset_id'                # 您的知识库ID
}

# 创建集成实例
geo_ragflow = GeoRAGFlowIntegration(ragflow_config)

# 查询知识库
results = geo_ragflow.query_geospatial_knowledge("您的查询内容")

# 检查结果
if results['success']:
    for result in results['results']:
        print(f"内容: {result['content']}")
        print(f"相似度: {result['score']}")
        print(f"来源: {result['source']}")
else:
    print(f"查询失败: {results['error']}")
```

### 2. 获取知识库信息

```python
info = geo_ragflow.get_knowledge_base_info()
if info['success']:
    print(info['dataset_info'])
else:
    print(f"获取知识库信息失败: {info['error']}")
```

### 3. 列出所有知识库

```python
from ragflow_integration import RAGFlowClient

client = RAGFlowClient('http://your-ragflow-host:port', 'your_api_key')
datasets = client.list_datasets()
for dataset in datasets:
    print(dataset)
```

## API接口说明

### RAGFlowClient类

- `list_datasets()`: 获取所有知识库列表
- `search_in_dataset(dataset_id, query, top_k=5, similarity_threshold=0.3)`: 在指定知识库中搜索
- `get_dataset_info(dataset_id)`: 获取知识库信息
- `upload_document(dataset_id, file_path)`: 上传文档到知识库

### GeoRAGFlowIntegration类

- `query_geospatial_knowledge(query)`: 查询地理空间相关知识
- `get_knowledge_base_info()`: 获取当前知识库信息

## 网络配置

确保您的geo项目能够访问RAGFlow服务：

- 如果在同一网络中，通常是直接访问
- 如果跨网络，可能需要配置网络路由或端口转发

## 错误处理

本集成框架已处理常见的API错误，包括：

- 网络连接错误
- API认证失败
- 知识库不存在
- 请求超时

## 集成到geo项目

1. 将`ragflow_integration.py`文件复制到您的geo项目中
2. 安装依赖项
3. 按照上述配置说明设置连接参数
4. 在您的代码中导入并使用`GeoRAGFlowIntegration`类

## 示例应用

```python
from ragflow_integration import GeoRAGFlowIntegration

# 配置参数
config = {
    'base_url': 'http://localhost:9380',
    'api_key': 'your_ragflow_api_key',
    'dataset_id': 'your_geo_knowledge_dataset_id'
}

# 初始化
geo_integration = GeoRAGFlowIntegration(config)

# 查询地理空间分析方法
results = geo_integration.query_geospatial_knowledge("地理空间数据处理方法")

if results['success']:
    print("找到以下相关信息:")
    for i, result in enumerate(results['results'], 1):
        print(f"{i}. {result['content'][:100]}...")
else:
    print(f"查询失败: {results['error']}")
```

## 常见问题

### 连接问题
- 确保RAGFlow服务正在运行
- 检查网络连接和防火墙设置
- 验证API密钥是否正确

### 认证问题
- 检查API密钥是否过期
- 确保API密钥具有访问相应知识库的权限

### 搜索结果不准确
- 检查知识库中是否包含相关文档
- 调整相似度阈值参数
- 优化查询语句

## 贡献

欢迎提交Issue和Pull Request来改进此集成框架。

## 许可证

本项目为开源项目，可用于学习和商业用途。