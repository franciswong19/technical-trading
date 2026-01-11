# utils/utils_report_css.py

def get_report_css():
    return """
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 40px; color: #333; line-height: 1.8; }
        
        /* Navy Blue Ribbon Headers */
        .header-ribbon { background-color: #002366; color: white; padding: 30px 40px; margin: -40px -40px 30px -40px; position: relative; }
        .header-ribbon h1 { margin: 0; font-size: 28px; font-weight: bold; }
        .header-ribbon h2 { margin: 5px 0 0 0; font-size: 20px; border: none; padding: 0; opacity: 0.9; color: white; }
        .confidential-tag { position: absolute; top: 15px; right: 20px; font-size: 11px; font-weight: bold; color: rgba(255,255,255,0.8); }
        
        .notice-box { border-left: 4px solid #002366; padding: 15px 20px; background: #f0f4fa; margin-bottom: 30px; font-size: 14px; line-height: 1.5; }
        .legal-footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 11px; color: #666; line-height: 1.5; text-align: justify; }
        
        .category-block { border-collapse: collapse; width: 1100px; table-layout: fixed; border: none; }
        .title-cell { font-size: 20px; font-weight: bold; color: #2c3e50; padding-bottom: 10px; white-space: nowrap; border: none; }
        .table-cell { width: 350px; vertical-align: top; border: none; padding-top: 5px; }
        .chart-cell { width: 800px; vertical-align: top; border: none; }
        .perf-table { width: 320px; border-collapse: collapse; font-size: 13px; line-height: 1.4; }
        .perf-table th, .perf-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .perf-table th { background: #f8f9fa; }
        
        h2 { font-size: 22px; border-bottom: 2px solid #eee; padding-bottom: 5px; margin-top: 40px; }
        p, ul { margin-bottom: 15px; }
    </style>
    """

def get_header_ribbon_html(title, sub_title):
    return f"""
    <div class="header-ribbon">
        <div class="confidential-tag">Private and Confidential. Not for circulation.</div>
        <h1>{title}</h1>
        <h2>{sub_title}</h2>
    </div>
    """