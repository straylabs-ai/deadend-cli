# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Language model utilities and helper functions for AI interactions.

This module provides utility functions and helper methods for working with
language models, including prompt processing, response parsing, and
model-specific functionality for the security research framework.
"""

# from anthropic import Anthropic
# from typing import Dict, List, Union
import re

# def llm_call(prompt: Union[str, List[Dict[str, str]]], system_prompt: str, model: str, tools: List[Dict[str, str]], api_key: str) -> str:
#     """
#     Send the request to the LLM with the defined client LLM

#     Args:
#         prompt (Union[str, List[Dict[str, str]]]): Prompt to the LLM.
#         system_prompt (str): System prompt associated with it. 
#         model (str): Model name. 
#         tools (List[Dict[str, str]]): List of tools to use when calling the llm
#         api_key (str): API Key of the LLM provider. 

#     Returns: 
#         str: Request reponse. 
#     """
#     client = Anthropic(api_key=api_key)
#     if type(prompt) is str:
#         messages = [{"role": "user", "content": prompt}]
#     else: 
#         messages = prompt
#     response = ""
#     with client.messages.stream(
#         max_tokens=4096,
#         system=system_prompt,
#         messages=messages,
#         model=model,
#         tools=tools,
#         temperature=0.5
#         ) as stream:
#         for text in stream.text_stream:
#             response = response + text
#             print(text, end="", flush=True)

#     return response


def extract_xml(text: str, tag: str) -> str:
    """
    Extracts the content of the specified XML tag from the given text. 
    Used for parsing structured responses 

    Args:
        text (str): The text containing the XML.
        tag (str): The XML tag to extract content from.

    Returns:
        str: The content of the specified XML tag, or an empty string if the tag is not found.
    """
    match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return match.group(1) if match else ""

def extract_xml_to_list(text: str, tag: str) -> list: 
    """
    Extracts the content of the specified XML tag from the given text. 
    Used for parsing structured responses 

    Args:
        text (str): The text containing the XML.
        tag (str): The XML tag to extract content from.

    Returns:
        list: list of the content for each occurence found
    """
    match = re.findall(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    
    return match
