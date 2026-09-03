import os
import time
from jinja2 import Environment, FileSystemLoader
from fastapi import HTTPException
from loguru import logger


class SiteGeneratorService:
    def __init__(self):
        # 定位目录
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.template_dir = os.path.join(self.base_dir, "templates")
        self.output_dir = os.path.join(self.base_dir, "static", "sites")

        # 初始化 Jinja2
        self.env = Environment(loader=FileSystemLoader(self.template_dir))

        # 确保目录存在
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_site(self, site_id: str, data: dict, template_id: str = "corporate"):
        """
        :param template_id: 'corporate' 或 'cowboy'
        """
        start = time.perf_counter()
        try:
            # 1. 模版映射表
            template_map = {"corporate": "corporate_v1.html", "cowboy": "cowboy_v1.html"}

            # 获取对应的文件名，默认为 corporate
            template_file = template_map.get(template_id, "corporate_v1.html")

            # 加载模版
            template = self.env.get_template(template_file)

            # 2. 渲染 HTML
            html_content = template.render(data)

            # 3. 创建站点子目录
            site_path = os.path.join(self.output_dir, site_id)
            if not os.path.exists(site_path):
                os.makedirs(site_path)

            # 4. 写入 index.html
            file_path = os.path.join(site_path, "index.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            logger.info(
                f"[SiteGen] 站点生成成功: site_id={site_id} template={template_file} "
                f"html_bytes={len(html_content.encode('utf-8'))} "
                f"elapsed={(time.perf_counter() - start) * 1000:.1f}ms"
            )
            return {"local_path": file_path, "preview_url": f"/static/sites/{site_id}/index.html"}
        except Exception as e:
            logger.error(f"[SiteGen] 站点生成失败: site_id={site_id} template={template_id} error={e}")
            raise HTTPException(status_code=500, detail=str(e))
