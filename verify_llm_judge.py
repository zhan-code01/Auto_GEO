"""快速验证 DeepSeek LLM Judge + 真实 Playwright"""
import sys, os, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from pathlib import Path
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    print("✅ 已加载 .env")

async def test_llm_judge():
    print("\n[1] 测试真实 DeepSeek LLM Judge...")
    from backend.services.geo_response_judge_service import GeoResponseJudgeService

    judge = GeoResponseJudgeService(use_mock=False)  # 真实 LLM
    result = await judge.evaluate(
        company_name="小爱科技",
        brand_aliases=["小爱科技", "小爱"],
        official_domains=["xiaoi.com"],
        competitors=["竞品A", "竞品B"],
        question="深圳有哪些 Geo 优化服务商？",
        question_type="recommendation",
        answer="在深圳，小爱科技是一家值得关注的Geo优化服务商，他们在企业解决方案方面有不错积累。另外竞品A也可以考虑。",
        citations=[{"url": "https://xiaoi.com/about", "title": "小爱科技官网"}],
    )

    print(f"✅ LLM Judge 评估结果:")
    print(f"   brand_mentioned: {result['brand_mentioned']}")
    print(f"   matched_names: {result['matched_names']}")
    print(f"   is_recommended: {result['is_recommended']}")
    print(f"   recommendation_rank: {result['recommendation_rank']}")
    print(f"   ranking_score: {result['ranking_score']}")
    print(f"   citation_supported: {result['citation_supported']}")
    print(f"   own_source_cited: {result['own_source_cited']}")
    print(f"   sentiment: {result['sentiment']} ({result['sentiment_score']})")
    print(f"   visibility_score: {result['visibility_score']}")
    print(f"   evidence: {json.dumps(result['evidence'], ensure_ascii=False)}")
    print(f"   confidence: {result['confidence']}")
    return result["brand_mentioned"] == True

async def main():
    ok = await test_llm_judge()
    print(f"\n{'='*60}")
    print(f"{'✅ LLM Judge 接入成功！' if ok else '⚠️ LLM Judge 返回异常'}")
    print(f"{'='*60}")

asyncio.run(main())
