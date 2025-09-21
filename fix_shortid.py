import re

def fix_short_id(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 正则匹配 short-id: 后的内容（只允许 0-9a-f 的 hex 字符）
    fixed_content = re.sub(
        r'(short-id:\s*)([0-9a-fA-F]+)',
        r'\1"\2"',
        content
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(fixed_content)

    print(f"处理完成 ✅，已保存到 {output_file}")

if __name__ == "__main__":
    fix_short_id("config.yaml", "config_fixed.yaml")
