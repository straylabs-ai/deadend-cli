# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Language-specific patterns for code analysis and chunking.

This module defines language-specific patterns for various programming languages,
including declaration patterns, comment patterns, and exclusion patterns used
in code analysis and semantic chunking for security research.
"""

from pydantic import BaseModel

class LanguagePatterns(BaseModel):
    language: str
    declaration_patterns: dict
    comments_patterns: dict
    exclude_patterns: dict


def get_language_patterns(language: str) -> LanguagePatterns | None :
    if language == 'javascript':
        return LanguagePatterns(
            language='javascript',
            declaration_patterns = {
                'function_declaration': 'Function Declaration',
                'class_declaration':'Class Declaration', 
                'statement_block': 'Block',
                'arrow_function': 'Arrow Function',
                'generator_function': 'Generator Function',
                'import_statement': 'Import Statement',
                'export_statement': 'Export Statement',
            },
            comments_patterns = {
                'comment' : 'Comment',
                'decorator' : 'Decorator'
            }, 
            exclude_patterns = {}
        )
    elif language == 'typescript':
        return LanguagePatterns(
            language='typescript',
            declaration_patterns = {
                'function_declaration': 'Function Declaration',
                'class_declaration':'Class Declaration', 
                'statement_block': 'Block',
                'arrow_function': 'Arrow Function',
                'generator_function': 'Generator Function',
                'import_statement': 'Import Statement',
                'export_statement': 'Export Statement',
                'interface_declaration': 'Interface',
                'type_alias_declaration': 'Type Alias',
            },
            comments_patterns = {
                'comment' : 'Comment',
                'decorator' : 'Decorator'
            }, 
            exclude_patterns= {}
        )
    elif language == 'html':
        return LanguagePatterns(
            language='html',
            declaration_patterns = {
                'script_element' :'script'
            },
            comments_patterns = {
                'comment' : 'Comment',
            },
            exclude_patterns = {
                'style_element': 'style'
            }
        )
    else: 
        return None 




