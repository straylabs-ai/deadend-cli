from src.code_indexer.code_chunker import CodeChunker
import jsbeautifier
from bs4 import BeautifulSoup as bs
import cssbeautifier

js_code =""
with open("./tests/fixtures/main.js") as file:
    js_code = file.read()

beautifier = jsbeautifier.Beautifier()
js_code_beauty = beautifier.beautify(js_code)
html_code =""
with open("./tests/fixtures/index.html") as file:
    html_code = file.read()

# html_soup_beauty = beautifier.beautify(str(html_code))
soup = bs(html_code, 'lxml')
for style_tag in soup.find_all("style"):
    style_tag.decompose()
# for style in soup.find_all("style"):
#     if style.string:
#         pretty_css = cssbeautifier.beautify(style.string)
#         style.string.replace_with(pretty_css)
html_soup = soup.prettify() 
chunker_html = CodeChunker("html")
chunks_html = chunker_html.chunk(str(html_soup), "html", 500)
res = ""
if chunks_html != None:
    for chunk_number, chunk_code in chunks_html.items():
        res = res + f"Chunk {chunk_number}:\n"
        res = res + "=" * 40+ "\n" 
        res = res + chunk_code + "\n" 
        res = res + "=" * 40+ "\n" 
with open('chunks_html.txt', 'w') as f:
    f.write(res) 
chunker = CodeChuncker("javascript")
chunks = chunker.chunk(str(js_code_beauty), "javascript", 500)
res = ""
if chunks != None:
    for chunk_number, chunk_code in chunks.items():
        res = res + f"Chunk {chunk_number}:\n"
        res = res + "=" * 40+ "\n" 
        res = res + chunk_code + "\n" 
        res = res + "=" * 40+ "\n" 
with open('chunks.txt', 'w') as f:
    f.write(res) 