import re

def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '', name)            # remove invalid chars
    name = re.sub(r'\(\d+\.\s*\)', '', name)            # remove stray numbers in parentheses
    name = re.sub(r'\s+', ' ', name).strip()            # collapse spaces
    return name