import cairosvg

# SVG 파일을 PNG로 변환하는 함수


def convert_svg_to_jpg(svg_url, output_file):
    try:
        cairosvg.svg2png(url=svg_url, write_to=output_file)
        return True
    except Exception as e:
        print(f"Error converting {svg_url} to {output_file}: {e}")
        return False


# 1부터 31까지의 SVG 파일을 JPG로 변환
for i in range(1, 32):
    svg_url = f"https://static.solved.ac/tier_small/{i}.svg"
    # JPG 대신 PNG 형식으로 저장 (cairosvg는 JPG 직접 지원 안 함)
    output_file = f"tier_{i}.png"
    result = convert_svg_to_jpg(svg_url, output_file)
    if result:
        print(f"Converted {svg_url} to {output_file}")
    else:
        print(f"Failed to convert {svg_url}")
