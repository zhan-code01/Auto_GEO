"""
RAGFlow连接测试脚本
用于测试与实际RAGFlow服务的连接
"""

import json
from ragflow_integration import RAGFlowClient, GeoRAGFlowIntegration
from _log_bridge import log_print


def load_config():
    """加载配置文件"""
    try:
        with open("config_example.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        return config["ragflow_config"]
    except FileNotFoundError:
        log_print("配置文件 config_example.json 未找到")
        log_print("请先创建配置文件或更新现有配置文件")
        return None
    except json.JSONDecodeError:
        log_print("配置文件格式错误，请检查JSON格式")
        return None


def test_connection(config):
    """测试与RAGFlow的连接"""
    log_print("开始连接测试...")
    log_print(f"目标URL: {config['base_url']}")

    try:
        client = RAGFlowClient(config["base_url"], config["api_key"])

        # 测试连接 - 获取数据集列表
        log_print("\n1. 测试API连接...")
        datasets = client.list_datasets()
        log_print(f"   ✓ 连接成功，找到 {len(datasets)} 个知识库")

        if datasets:
            log_print("\n   知识库列表:")
            for i, dataset in enumerate(datasets[:5], 1):  # 只显示前5个
                log_print(f"   {i}. {dataset.get('name', 'Unknown')} (ID: {dataset.get('id', 'Unknown')})")

        return True, datasets

    except Exception as e:
        log_print(f"   ✗ 连接失败: {e}")
        log_print("\n可能的原因:")
        log_print("   - RAGFlow服务未运行")
        log_print("   - 网络连接问题")
        log_print("   - API密钥错误或过期")
        log_print("   - URL配置错误")
        return False, []


def test_search_functionality(config, dataset_id):
    """测试搜索功能"""
    log_print(f"\n2. 测试搜索功能 (知识库ID: {dataset_id})...")

    try:
        client = RAGFlowClient(config["base_url"], config["api_key"])

        # 执行测试搜索
        result = client.search_in_dataset(dataset_id=dataset_id, query="测试查询", top_k=3)

        log_print("   ✓ 搜索请求发送成功")

        # 检查结果
        chunks = result.get("chunks", result.get("data", []))
        log_print(f"   返回 {len(chunks)} 个结果")

        if chunks:
            log_print("   前几个结果预览:")
            for i, chunk in enumerate(chunks[:2], 1):
                content_preview = chunk.get("content", "")[:100] + "..."
                score = chunk.get("score", chunk.get("similarity", 0))
                log_print(f"   {i}. 相似度: {score:.3f}, 内容: {content_preview}")

        return True

    except Exception as e:
        log_print(f"   ✗ 搜索失败: {e}")
        return False


def test_geo_integration(config):
    """测试GeoRAGFlowIntegration类"""
    log_print("\n3. 测试GeoRAGFlowIntegration集成...")

    try:
        # 创建集成实例
        geo_integration = GeoRAGFlowIntegration(config)

        # 尝试获取知识库信息
        info_result = geo_integration.get_knowledge_base_info()
        if info_result["success"]:
            log_print("   ✓ GeoRAGFlowIntegration初始化成功")
        else:
            log_print(f"   ! GeoRAGFlowIntegration初始化有警告: {info_result['error']}")

        # 尝试执行查询（使用安全的测试查询）
        query_result = geo_integration.query_geospatial_knowledge("测试查询")
        if query_result["success"]:
            log_print(f"   ✓ 查询功能正常，返回 {len(query_result['results'])} 个结果")
        else:
            log_print(f"   ! 查询功能有警告: {query_result['error']}")

        return True

    except Exception as e:
        log_print(f"   ✗ GeoRAGFlowIntegration测试失败: {e}")
        return False


def run_complete_test():
    """运行完整的连接测试"""
    log_print("=" * 60)
    log_print("RAGFlow连接测试")
    log_print("=" * 60)

    # 加载配置
    config = load_config()
    if not config:
        return False

    log_print("使用配置:")
    log_print(f"  URL: {config['base_url']}")
    log_print(f"  API Key: {'*' * (len(config['api_key']) - 4) + config['api_key'][-4:]}")  # 隐藏API密钥
    log_print(f"  Dataset ID: {config['dataset_id']}")

    log_print("\n注意: 此测试将尝试连接到您的RAGFlow服务。")
    log_print("请确保:")
    log_print("  1. RAGFlow服务正在运行")
    log_print("  2. 网络连接正常")
    log_print("  3. API密钥正确有效")
    log_print("  4. 知识库ID存在")

    input("\n按Enter键继续测试，或Ctrl+C取消...")

    # 执行连接测试
    connection_success, datasets = test_connection(config)

    if not connection_success:
        log_print("\n🚨 连接失败，无法继续测试")
        return False

    # 如果没有数据集，提示用户
    if not datasets:
        log_print("\n⚠️  没有找到任何知识库")
        log_print("请先在RAGFlow中创建知识库并添加文档")
        return True  # 连接成功，只是没有数据集

    # 使用第一个数据集进行搜索测试
    dataset_id = config["dataset_id"]  # 使用配置中的ID
    if dataset_id not in [d.get("id") for d in datasets]:
        log_print(f"\n⚠️  配置中的数据集ID '{dataset_id}' 不存在")
        log_print("使用第一个可用的数据集进行测试...")
        dataset_id = datasets[0].get("id")
        log_print(f"使用数据集ID: {dataset_id}")

    # 测试搜索功能
    search_success = test_search_functionality(config, dataset_id)

    # 测试集成类
    integration_success = test_geo_integration(config)

    log_print("\n" + "=" * 60)
    log_print("测试总结:")
    log_print(f"  连接测试: {'✓ 通过' if connection_success else '✗ 失败'}")
    log_print(f"  搜索测试: {'✓ 通过' if search_success else '✗ 失败'}")
    log_print(f"  集成测试: {'✓ 通过' if integration_success else '✗ 失败'}")

    if connection_success and search_success and integration_success:
        log_print("\n🎉 所有测试通过! 您可以正常使用集成框架。")
        log_print("\n下一步建议:")
        log_print("  1. 在您的geo项目中导入ragflow_integration模块")
        log_print("  2. 使用相同的配置初始化GeoRAGFlowIntegration")
        log_print("  3. 调用query_geospatial_knowledge方法进行知识库查询")
        return True
    else:
        log_print("\n⚠️  部分测试失败，请检查配置和RAGFlow服务状态。")
        return False


if __name__ == "__main__":
    run_complete_test()
