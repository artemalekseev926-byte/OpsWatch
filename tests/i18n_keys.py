from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "opswatch"
CYR = re.compile(r"[А-Яа-яЁё]")
CALLS = {"tr", "ts", "tl", "_"}
SKIP_ASSIGN = {"DEFAULT_TEMPLATES"}


def _string(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def python_keys() -> set[str]:
    keys: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if name in CALLS and node.args:
                    value = _string(node.args[0])
                    if value and CYR.search(value):
                        keys.add(value)
                continue
            value = _string(node)
            if not value or not CYR.search(value):
                continue
            chain = []
            current = parents.get(node)
            while current is not None:
                chain.append(current)
                current = parents.get(current)
            in_field = any(
                isinstance(item, ast.Call) and getattr(item.func, "id", getattr(item.func, "attr", "")) == "Field" for item in chain
            )
            if not in_field and any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.JoinedStr)) for item in chain):
                continue
            if any(isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id in SKIP_ASSIGN for t in item.targets) for item in chain):
                continue
            if isinstance(parents.get(node), ast.Expr):
                continue
            keys.add(value)
    return keys


def js_keys() -> set[str]:
    source = (PACKAGE / "web" / "static" / "app.js").read_text(encoding="utf-8")
    keys = set()
    for match in re.finditer(r'\bt\("((?:[^"\\]|\\.)*)"', source):
        value = json.loads('"' + match.group(1) + '"')
        if CYR.search(value):
            keys.add(value)
    return keys


def all_keys() -> set[str]:
    return python_keys() | js_keys()


def load_catalog(lang: str = "en") -> dict[str, str]:
    path = PACKAGE / "locales" / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)[^}]*\}", text))


if __name__ == "__main__":
    catalog = load_catalog()
    missing = sorted(all_keys() - set(catalog))
    if "--json" in sys.argv:
        print(json.dumps(missing, ensure_ascii=False, indent=1))
    else:
        for key in missing:
            print(repr(key))
        print(len(missing), "missing", file=sys.stderr)
