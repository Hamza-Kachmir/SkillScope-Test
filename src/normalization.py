import re
from collections import defaultdict

def get_canonical_form(skill_name: str) -> str:
    if not isinstance(skill_name, str): return ""
    return re.sub(r'[^a-z0-9]', '', skill_name.lower())

def choose_best_representation(skill_variants: list[str]) -> str:
    if not skill_variants: return ""
    def sort_key(skill):
        has_space = ' ' in skill.strip()
        uppercase_count = sum(1 for char in skill if char.isupper())
        length = len(skill)
        return (not has_space, -uppercase_count, -length, skill)
    return sorted(skill_variants, key=sort_key)[0]

def build_normalization_map(skill_list: list[str]) -> dict[str, str]:
    canonical_map = defaultdict(list)
    for skill in set(skill_list):
        canonical_form = get_canonical_form(skill)
        if canonical_form:
            canonical_map[canonical_form].append(skill)
    normalization_map = {}
    for variants in canonical_map.values():
        best_representation = choose_best_representation(variants)
        for variant in variants:
            normalization_map[variant] = best_representation
    return normalization_map

def create_skill_regex(skill_name: str) -> str:
    parts = [re.escape(part) for part in skill_name.split()]
    pattern_str = r'(\s*-?)'.join(parts) if len(parts) > 1 else parts[0]
    return r'\b' + pattern_str + r'\b'