import re
import os

class JSObfuscatedProcessor:
    def __init__(self):
        self.target_pattern = r'\.responseModalities&&\(\('
        self.yield_pattern = r'(\w+)\s*=\s*yield\s*_\.(\w+)\s*\(\s*(\w+)\.(\w+)\s*,\s*\w+\s*\)\s*;?'

    def process_and_get_modified_string(self, js_code: str):
        """
        在内存中处理JS代码字符串，并返回修改后的内容和捕获的数据。
        这是本场景的核心方法。

        :param js_code: 原始JS代码字符串
        :return: A tuple (modified_code, captured_data) or (None, None) if failed.
        """
        # 1. 查找所有匹配的目标特征字符串 (锚点)
        all_anchor_matches = list(re.finditer(self.target_pattern, js_code))

        # 2. 检查是否有至少两个匹配项，并选择第二个
        if len(all_anchor_matches) < 2:
            print(f"[Processor] 错误: 只找到了 {len(all_anchor_matches)} 个锚点，需要至少 2 个。")
            return None, None

        second_anchor_match = all_anchor_matches[1]
        print(f"[Processor] 找到了 {len(all_anchor_matches)} 个锚点。使用第二个，位置 at {second_anchor_match.start()}")

        # 3. 从第二个锚点的结束位置开始查找
        search_start_pos = second_anchor_match.end()
        substring_to_search = js_code[search_start_pos:]
        yield_match = re.search(self.yield_pattern, substring_to_search)

        if not yield_match:
            print(f"[Processor] 在第二个特征字符串之后未找到匹配的双参数 yield 模式")
            return None, None

        actual_pos = search_start_pos + yield_match.start()
        print(f"[Processor] 找到第一个双参数 yield 匹配 at position {actual_pos}")

        # 4. 从匹配中动态捕获所有随机变量名
        var_name, func_name, obj_name, prop_name = yield_match.groups()
        print(f"[Processor] 捕获成功: {func_name} 和 {prop_name}")

        # 5. 准备要插入的代码
        insert_code = f"window.MY_{func_name.upper()}=_.{func_name};\nwindow.MY_{prop_name.upper()}={obj_name}.{prop_name};\n"

        # 6. 应用修改
        line_start = js_code.rfind('\n', 0, actual_pos) + 1
        indent_match = re.match(r'[\s\t]*', js_code[line_start:])
        indent = indent_match.group(0) if indent_match else ''
        indented_code = '\n'.join(indent + line for line in insert_code.strip().split('\n')) + '\n' + indent

        modified_code = js_code[:actual_pos] + indented_code + js_code[actual_pos:]

        print(f"[Processor] 调试代码已准备好注入。")

        # 7. 准备返回的数据
        captured_data = {
            'func_name': func_name,
            'prop_name': prop_name
        }

        return modified_code, captured_data


def main():
    processor = JSObfuscatedProcessor()
    print("JS混淆代码处理器 (注入并返回捕获名版)")
    print("=" * 50)

    file_path_to_process = '/app/services/m=_b-76282a03.js'

    print(f"\n--- 尝试处理文件: {file_path_to_process} ---")
    if os.path.exists(file_path_to_process):
        # 现在接收两个返回值：一个布尔型的成功标志，一个包含数据的字典
        # 假设文件名是 example.txt
        with open(file_path_to_process, "r", encoding="utf-8") as f:
            content = f.read()

        print(content)  # content 是字符串

        modified_code, captured_data = processor.process_and_get_modified_string(content)

        # 生成新文件路径，加上 modified 后缀


        base, ext = os.path.splitext(file_path_to_process)
        modified_path = base + "_modified" + ext

        # 写入新文件
        with open(modified_path, "w", encoding="utf-8") as f:
            f.write(modified_code)

        print("\n文件处理成功！")

        # --- 新增功能: 使用返回的数据格式化 js_script ---
        print("\n--- 使用捕获的变量名格式化 eval 字符串 ---")

        # 从返回的字典中获取捕获到的名字
        func_name = captured_data['func_name']  # 例如 'MA'
        prop_name = captured_data['prop_name']  # 例如 'za'

        # 假设这是您动态生成的哈希值
        sha256_hash = "your_dynamic_sha256_hash_here"

        # 使用 f-string 将 'MYGA' 和 'MYZA' 替换为动态生成的调试变量名
        js_script = f"""
        async () => {{
            let y = await window.MY_{func_name.upper()}(window.MY_{prop_name.upper()}, "{sha256_hash}");
            return y;
        }}
        """

        print("格式化后的 js_script 字符串:")
        print(js_script)


    else:
        print(f"错误：文件不存在, 请检查路径。")


if __name__ == "__main__":
    main()