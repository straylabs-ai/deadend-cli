# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Code splitting and chunking system for source code analysis.

This module provides functionality to split and chunk source code files
using tree-sitter parsers for various programming languages, enabling
semantic code analysis and embedding generation for security research.
"""
from typing import List
import tree_sitter_javascript as tree_js
import tree_sitter_typescript as tree_ts
import tree_sitter_html as tree_html
import tree_sitter_css as tree_css
import tree_sitter_markdown as tree_markdown
from semantic_text_splitter import CodeSplitter, TextSplitter
from jsbeautifier import Beautifier



class Chunker:
    """A code chunker that splits source code files into semantic chunks.
    
    This class provides functionality to split source code files into chunks
    using tree-sitter parsers for various programming languages. It supports
    both code files (JavaScript, TypeScript, HTML, CSS) and text files (Markdown)
    with different chunking strategies based on the file type.
    
    Attributes:
        file_path (str): Path to the file to be chunked.
        language (str): Programming language of the file.
        code (bool): Whether the file contains code (True) or text (False).
        tiktoken_model (str): Tiktoken model to use for token counting.
    """
    
    def __init__(self, file_path: str, language: str, code: bool, tiktoken_model: str):
        """Initialize the Chunker with file information and chunking parameters.
        
        Args:
            file_path (str): Path to the file to be chunked.
            language (str): Programming language of the file (e.g., 'javascript', 'typescript', 'html', 'css', 'markdown').
            code (bool): Whether the file contains code (True) or text content (False).
            tiktoken_model (str): Tiktoken model to use for token counting and chunk sizing.
        """
        self.file_path = file_path
        self.language = language
        self.code = code
        self.tiktoken_model = tiktoken_model
    
    def chunk_file(self, size_chunk: int) -> List[str]:
        """Split the file into chunks based on the specified chunk size.
        
        For code files, this method uses tree-sitter parsers to create semantic
        chunks that respect code structure. For text files, it uses a text splitter
        that works with the markdown language parser.
        
        Args:
            size_chunk (int): Maximum size of each chunk in tokens.
            
        Returns:
            List[str]: List of text chunks created from the file.
            
        Raises:
            FileNotFoundError: If the file_path does not exist.
            ValueError: If the language is not supported.
        """
        splitter = None
        chunks = []
        if self.code:
            if self.language == 'javascript':
                splitter = CodeSplitter.from_tiktoken_model(tree_js.language(),self.tiktoken_model, size_chunk)
            elif self.language == 'typescript':
                splitter = CodeSplitter.from_tiktoken_model(tree_ts.language_typescript(), self.tiktoken_model, size_chunk)
            elif self.language == 'typescriptx':
                splitter = CodeSplitter(tree_ts.language_tsx(), size_chunk)
            elif self.language == 'html':
                splitter = CodeSplitter.from_tiktoken_model(tree_html.language(), self.tiktoken_model, size_chunk)
            elif self.language == 'css':
                splitter = CodeSplitter.from_tiktoken_model(tree_css.language(), self.tiktoken_model, size_chunk)
            beautifier = Beautifier()
            code_content = ""
            with open(self.file_path, encoding='utf-8') as f:
                code_content = f.read()
            code_beautified = beautifier.beautify(code_content)

            chunks = splitter.chunks(code_beautified)
            return chunks
        else:
            if self.language == 'markdown':
                splitter = TextSplitter.from_tiktoken_model(tree_markdown.language(), self.tiktoken_model, size_chunk)
            with open(self.file_path, encoding='utf-8') as f:
                document_content = f.read()
            chunks = splitter.chunks(document_content)
            return chunks
