import streamlit as st
import graphviz
import pandas as pd
from docx import Document
from docx.shared import Inches
import re
import textwrap
import io

# ==========================================
# 底層解析引擎庫
# ==========================================
def parse_indentation(text):
    nodes_dict = {}
    edges = []
    stack = []
    node_counter = 0
    def get_id():
        nonlocal node_counter
        node_counter += 1
        return f"IND_{node_counter}"

    for line in text.strip().split('\n'):
        if not line.strip(): continue
        level = len(line) - len(line.lstrip(' \t'))
        label = line.strip()
        
        node_id = get_id()
        nodes_dict[node_id] = {"label": label, "type": "standard"}
        
        while stack and stack[-1][0] >= level: stack.pop()
        if stack: edges.append((stack[-1][1], node_id))
        stack.append((level, node_id))
        
    return nodes_dict, edges

def parse_mermaid(text):
    nodes_dict = {}
    edges = []
    node_pattern = re.compile(r'([A-Za-z0-9_]+)(?:\[|\(|\{)(.*?)(?:\]|\)|\})')
    
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('%%') or line.startswith('graph'): continue
            
        if '-->' in line:
            parts = [p.strip() for p in line.split('-->')]
            chain_ids = []
            
            for part in parts:
                match = node_pattern.search(part)
                if match:
                    node_id = match.group(1).strip()
                    label = match.group(2).replace('<br>', '\n').strip()
                    nodes_dict[node_id] = {"label": label, "type": "standard"}
                    chain_ids.append(node_id)
                else:
                    node_id = part.strip()
                    if node_id:
                        if node_id not in nodes_dict:
                            nodes_dict[node_id] = {"label": node_id, "type": "standard"}
                        chain_ids.append(node_id)
            
            for i in range(len(chain_ids) - 1): edges.append((chain_ids[i], chain_ids[i+1]))
                
    return nodes_dict, edges

def parse_clinical(text):
    nodes_dict = {"Root": {"label": "臨床鑑別與決策\nClinical Diagnosis & Decision", "type": "root"}}
    edges = []
    current_l1 = current_l2 = last_disease_id = None
    node_counter = 0
    def get_id(prefix):
        nonlocal node_counter
        node_counter += 1
        return f"{prefix}_{node_counter}"
        
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line: continue
        
        if re.match(r'^\d+\.', line):
            l1_id = get_id("L1")
            nodes_dict[l1_id] = {"label": line, "type": "main"}
            edges.append(("Root", l1_id))
            current_l1, current_l2, last_disease_id = l1_id, None, None
            
        elif '➔' in line:
            parts = line.split('➔')
            sym_id, dis_id = get_id("SYM"), get_id("DIS")
            nodes_dict[sym_id] = {"label": parts[0].strip(), "type": "symptom"}
            nodes_dict[dis_id] = {"label": parts[1].strip(), "type": "disease"}
            
            if current_l2: edges.append((current_l2, sym_id))
            elif current_l1: edges.append((current_l1, sym_id))
            edges.append((sym_id, dis_id))
            last_disease_id = dis_id
            
        elif any(line.startswith(kw) for kw in ["治療", "配伍", "禁忌"]):
            trt_id = get_id("TRT")
            nodes_dict[trt_id] = {"label": line, "type": "treatment"}
            if last_disease_id: edges.append((last_disease_id, trt_id))
            elif current_l2: edges.append((current_l2, trt_id))
            elif current_l1: edges.append((current_l1, trt_id))
            
        else:
            if current_l1:
                l2_id = get_id("L2")
                nodes_dict[l2_id] = {"label": line, "type": "sub"}
                edges.append((current_l1, l2_id))
                current_l2, last_disease_id = l2_id, None

    return nodes_dict, edges

def auto_detect_and_parse(text):
    if '-->' in text or 'graph LR' in text or 'graph TB' in text: return parse_mermaid(text), "Mermaid 語法模式"
    elif '➔' in text: return parse_clinical(text), "臨床醫學判別模式"
    else: return parse_indentation(text), "空白縮排模式"

def format_label_wrap(text, width):
    lines = text.split('\n')
    return '\n'.join([textwrap.fill(line, width=width) if len(line) > width else line for line in lines])

# ==========================================
# 介面配置與主程式邏輯
# ==========================================
st.set_page_config(page_title="專業決策樹生成器", layout="wide")
st.title("專業決策樹 Decision-tree (心智圖)生成器")

col1, col2 = st.columns([1, 1.5])

with col1:
    st.markdown("### 參數設定")
    input_text = st.text_area("貼上結構文字", height=350, placeholder="自動判別格式：空白縮排 / Notebook LM / 臨床格式...")
    
    dir_col, style_col = st.columns(2)
    with dir_col: direction = st.radio("排版方向", ["橫式 (左至右)", "直式 (上至下)"])
    with style_col: line_style = st.radio("連線風格", ["直角折線", "彎曲線條"])
    
    shape_col, density_col = st.columns(2)
    with shape_col: node_shape = st.radio("節點形狀", ["方框", "圓框", "無框"])
    with density_col: density = st.radio("排版密度", ["緊密", "適中", "鬆散"])
    
    wrap_width = st.slider("自動斷行字數限制 (字/行)", 5, 40, 15)

with col2:
    st.markdown("### 分析結果與輸出")
    if input_text.strip():
        # 1. 執行運算
        (nodes_dict, edges), detected_mode = auto_detect_and_parse(text=input_text)
        st.success(f"系統判定格式：**{detected_mode}**")

        # 2. 參數映射
        dir_map = {"橫式 (左至右)": "LR", "直式 (上至下)": "TB"}
        line_map = {"直角折線": "ortho", "彎曲線條": "spline"}
        shape_map = {"方框": "box", "圓框": "ellipse", "無框": "plaintext"}
        density_map = {
            "緊密": {"nodesep": "0.1", "ranksep": "0.2"},
            "適中": {"nodesep": "0.4", "ranksep": "0.5"},
            "鬆散": {"nodesep": "0.8", "ranksep": "1.0"}
        }

        # 3. 建立 Graphviz
        dot = graphviz.Digraph(format='png')
        dot.attr(rankdir=dir_map[direction], splines=line_map[line_style], nodesep=density_map[density]["nodesep"], ranksep=density_map[density]["ranksep"])
        selected_shape = shape_map[node_shape]
        
        for node_id, data in nodes_dict.items():
            node_type = data.get("type", "standard")
            formatted_label = format_label_wrap(data["label"], int(wrap_width))
            
            if node_type == "disease":
                dot.node(node_id, formatted_label, shape=selected_shape, style="filled", fillcolor="#ffcccc", fontname="WenQuanYi Zen Hei", fontsize="12")
            elif node_type == "treatment":
                dot.node(node_id, formatted_label, shape=selected_shape, style="filled", fillcolor="#ccffcc", fontname="WenQuanYi Zen Hei", fontsize="11")
            elif node_type == "root":
                dot.node(node_id, formatted_label, shape=selected_shape, style="filled", fillcolor="#e0e0e0", fontname="WenQuanYi Zen Hei", fontsize="14", fontweight="bold")
            else:
                dot.node(node_id, formatted_label, shape=selected_shape, fontname="WenQuanYi Zen Hei", fontsize="12")

        for parent, child in edges: dot.edge(parent, child)

        # 4. 產生多格式數據流 (不存硬碟，直接轉 Bytes 以利下載)
        png_data = dot.pipe(format='png')
        pdf_data = dot.pipe(format='pdf')
        svg_data = dot.pipe(format='svg')
        
        # 顯示預覽圖
        st.image(png_data, use_container_width=True)
        
        # 準備 Word
        doc = Document()
        doc.add_heading(f'決策分析結構 ({detected_mode})', 0)
        doc.add_picture(io.BytesIO(png_data), width=Inches(6.5))
        doc.add_heading('原始數據記錄', level=1)
        for line in input_text.strip().split('\n'): doc.add_paragraph(line)
        docx_output = io.BytesIO()
        doc.save(docx_output)
        docx_data = docx_output.getvalue()

        # 準備 Excel
        readable_edges = [(nodes_dict[p]["label"].replace('\n', ' '), nodes_dict[c]["label"].replace('\n', ' ')) for p, c in edges]
        df = pd.DataFrame(readable_edges, columns=["上層節點", "下層節點"])
        excel_output = io.BytesIO()
        df.to_excel(excel_output, index=False)
        excel_data = excel_output.getvalue()

        # 準備 Markdown
        md_data = f"# 決策結構數據 ({detected_mode})\n\n```text\n{input_text.strip()}\n```".encode('utf-8')

        # 5. 提供全面下載按鈕
        st.markdown("#### 📥 檔案匯出")
        dl_col1, dl_col2, dl_col3 = st.columns(3)
        dl_col4, dl_col5, dl_col6 = st.columns(3)
        
        dl_col1.download_button("PDF 高清報告", data=pdf_data, file_name="Decision_Tree.pdf", mime="application/pdf", use_container_width=True)
        dl_col2.download_button("PNG 預覽圖", data=png_data, file_name="Decision_Tree.png", mime="image/png", use_container_width=True)
        dl_col3.download_button("SVG 向量圖", data=svg_data, file_name="Decision_Tree.svg", mime="image/svg+xml", use_container_width=True)
        dl_col4.download_button("WORD 編輯檔", data=docx_data, file_name="Decision_Tree.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        dl_col5.download_button("EXCEL 關聯表", data=excel_data, file_name="Decision_Tree.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        dl_col6.download_button("MD 原始文字", data=md_data, file_name="Decision_Tree.md", mime="text/markdown", use_container_width=True)
