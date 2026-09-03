"""
RAGFlow服务状态检查脚本
用于检查RAGFlow服务是否正在运行
"""

import requests
import json
import os
from ragflow_integration import RAGFlowClient
from _log_bridge import log_print


def check_ragflow_status(base_url):
    """检查RAGFlow服务状态"""
    log_print(f"检查RAGFlow服务状态: {base_url}")

    try:
        # 尝试访问RAGFlow的API端点
        response = requests.get(f"{base_url}/api/v1/health", timeout=10)
        if response.status_code == 200:
            log_print("✓ RAGFlow服务正在运行")
            return True
        else:
            log_print(f"✗ RAGFlow服务响应异常，状态码: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        log_print("✗ 无法连接到RAGFlow服务，请确保服务正在运行")
        return False
    except requests.exceptions.Timeout:
        log_print("✗ 连接RAGFlow服务超时")
        return False
    except Exception as e:
        log_print(f"✗ 检查RAGFlow服务时出错: {e}")
        return False


def load_config():
    """加载配置文件"""
    config_path = "config.json"
    if not os.path.exists(config_path):
        config_path = "config_example.json"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config["ragflow_config"]
    except FileNotFoundError:
        log_print(f"配置文件 {config_path} 未找到")
        return None
    except json.JSONDecodeError:
        log_print("配置文件格式错误，请检查JSON格式")
        return None


def test_api_key_validity(config):
    """测试API密钥是否有效"""
    log_print("\n测试API密钥有效性...")

    try:
        client = RAGFlowClient(config["base_url"], config["api_key"])

        # 尝试列出数据集，验证API密钥
        datasets = client.list_datasets()
        log_print(f"✓ API密钥有效，找到 {len(datasets)} 个知识库")

        if datasets:
            log_print("  知识库列表:")
            for i, dataset in enumerate(datasets[:5], 1):
                log_print(f"  {i}. {dataset.get('name', 'Unknown')} (ID: {dataset.get('id', 'Unknown')})")

        return True, datasets
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            log_print("✗ API密钥无效或已过期")
        elif e.response.status_code == 403:
            log_print("✗ API密钥无权限访问")
        else:
            log_print(f"✗ API请求失败: {e}")
        return False, []
    except Exception as e:
        log_print(f"✗ 测试API密钥时出错: {e}")
        return False, []


def main():
    log_print("=" * 60)
    log_print("RAGFlow服务状态检查")
    log_print("=" * 60)

    # 加载配置
    config = load_config()
    if not config:
        log_print("无法加载配置，请确保config.json或config_example.json存在")
        return False

    log_print("使用配置:")
    log_print(f"  URL: {config['base_url']}")
    log_print(f"  API Key: {'*' * (len(config['api_key']) - 4) + config['api_key'][-4:]}")  # 隐藏API密钥
    log_print(f"  Dataset ID: {config['dataset_id']}")

    # 检查服务状态
    service_running = check_ragflow_status(config["base_url"])

    if not service_running:
        log_print("\n⚠️  RAGFlow服务未运行")
        log_print(f"请确保RAGFlow服务在 {config['base_url']} 上运行")
        log_print("如果您使用不同的端口或地址，请更新配置文件")
        return False

    # 测试API密钥
    api_valid, datasets = test_api_key_validity(config)

    if not api_valid:
        log_print("\n⚠️  API密钥无效")
        log_print("请检查:")
        log_print("  1. API密钥是否正确")
        log_print("  2. API密钥是否已过期")
        log_print("  3. API密钥是否有足够的权限")
        log_print("\n获取API密钥方法:")
        log_print("  1. 登录RAGFlow界面")
        log_print("  2. 点击右上角用户头像")
        log_print("  3. 选择'API' -> 'RAGFlow API'")
        log_print("  4. 复制API Key")
        return False

    log_print("\n✓ 所有检查通过!")
    log_print("✓ RAGFlow服务运行正常")
    log_print("✓ API密钥有效")
    log_print("✓ 可以进行连接测试")

    if datasets:
        log_print("\n下一步您可以:")
        log_print("  1. 运行连接测试: python test_connection.py")
        log_print("  2. 在您的geo项目中使用集成框架")
    else:
        log_print("\n注意: 没有找到知识库")
        log_print("请先在RAGFlow中创建知识库并添加文档")

    return True


if __name__ == "__main__":
    main()
