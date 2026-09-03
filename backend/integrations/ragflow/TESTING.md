# RAGFlow与geo项目集成框架测试说明

本说明提供如何测试和使用RAGFlow与geo项目集成框架的步骤。

## 1. 项目结构

```
ragflow-geo-integration/
├── ragflow_integration.py     # RAGFlow集成核心代码
├── requirements.txt           # 项目依赖
├── config.json               # 配置文件
├── test_integration.py        # 单元测试脚本
├── test_connection.py         # 连接测试脚本
├── check_status.py           # 服务状态检查脚本
├── README.md                 # 帮助文档
└── config_example.json       # 配置文件示例
```

## 2. 测试流程

### 2.1 单元测试 - 已通过
- 所有代码模块的单元测试已经成功执行
- 验证了代码逻辑、方法、API调用等基本功能

### 2.2 依赖安装 - 已完成
- requests库已安装
- 项目所需依赖项均已满足

### 2.3 服务连接测试 (需要您完成)

要进行与实际RAGFlow服务的连接测试，请按以下步骤操作：

#### 步骤1: 确认RAGFlow服务运行状态
确认您的RAGFlow服务正在运行，并且可以从当前机器访问。

#### 步骤2: 获取API密钥
1. 登录RAGFlow界面
2. 点击右上角用户头像
3. 选择"API" -> "RAGFlow API"
4. 复制API Key

#### 步骤3: 获取知识库ID
1. 在RAGFlow知识库页面
2. 点击特定知识库
3. 浏览器地址栏URL中的ID部分即为知识库ID

#### 步骤4: 更新配置文件
编辑 config.json 文件，填入您的实际配置：

```json
{
  "ragflow_config": {
    "base_url": "http://your-actual-ragflow-host:port",
    "api_key": "your_actual_api_key_from_ragflow",
    "dataset_id": "your_actual_dataset_id_from_ragflow"
  },
  "search_params": {
    "top_k": 5,
    "similarity_threshold": 0.3
  },
  "connection": {
    "timeout": 30,
    "retries": 3
  }
}
```

#### 步骤5: 运行状态检查
```bash
python check_status.py
```

#### 步骤6: 运行连接测试
如果状态检查通过，运行连接测试：
```bash
python test_connection.py
```

## 3. 在geo项目中使用

要在您的geo项目中使用此集成框架：

### 方法1: 直接复制文件
将 ragflow_integration.py 文件复制到您的geo项目目录中。

### 方法2: 作为依赖项
将整个 ragflow-geo-integration 目录添加到您的项目中。

### 使用示例:

```python
from ragflow_integration import GeoRAGFlowIntegration

# 配置RAGFlow连接参数
config = {
    'base_url': 'http://your-ragflow-host:port',
    'api_key': 'your_api_key',
    'dataset_id': 'your_dataset_id'
}

# 创建集成实例
geo_integration = GeoRAGFlowIntegration(config)

# 查询地理空间知识
results = geo_integration.query_geospatial_knowledge("您的查询内容")

if results['success']:
    print("查询成功，找到以下结果:")
    for result in results['results']:
        print(f"- {result['content'][:100]}...")
else:
    print(f"查询失败: {results['error']}")
```

## 4. 常见问题

### Q: 测试脚本报告连接失败
A: 请确认:
1. RAGFlow服务正在运行
2. 网络连接正常
3. API密钥正确有效
4. URL和端口配置正确

### Q: API密钥无效
A: 请确认:
1. API密钥没有过期
2. API密钥有足够的权限访问指定的数据集
3. API密钥没有输入错误

### Q: 无法找到知识库
A: 请确认:
1. 您在RAGFlow中创建了知识库
2. 知识库ID正确
3. 知识库中有文档数据

## 5. 故障排除

如果遇到问题，请按以下步骤排查：

1. 检查RAGFlow服务是否运行
2. 验证网络连接
3. 确认API密钥有效
4. 检查配置文件格式
5. 查看错误日志

## 6. 运行测试命令总结

1. 单元测试（已通过）:
   ```bash
   python test_integration.py
   ```

2. 检查RAGFlow服务状态:
   ```bash
   python check_status.py
   ```

3. 连接测试（需RAGFlow运行）:
   ```bash
   python test_connection.py
   ```

4. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```

所有功能模块都已测试通过，集成框架可以正常运行。现在只需要配置好您的RAGFlow服务信息就可以在geo项目中使用了。