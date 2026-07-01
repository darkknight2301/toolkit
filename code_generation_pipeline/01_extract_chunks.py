"""
extract_chunks_ast.py
----------------------
AST-based C++ chunk extractor using tree-sitter.

Replaces the regex/brace-matching prototype. Correctly handles multi-line
signatures, constructor initializer lists, nested namespaces, and inheritance
-- things a regex approach silently mis-parses.

Output: one JSON record per class / free function / method, each tagged
with file, namespace, class, signature, doc_comment, body, and a rough
list of referenced identifiers ("calls") for building the dependency graph
later.
"""

import json
import sys
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_cpp as tscpp

CPP_LANGUAGE = Language(tscpp.language())
parser = Parser(CPP_LANGUAGE)


def text(node, src):
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def get_doc_comment(node, src):
    prev = node.prev_sibling
    comments = []
    while prev is not None and prev.type == "comment":
        comments.insert(0, text(prev, src).strip())
        prev = prev.prev_sibling
    if not comments:
        return None
    cleaned = []
    for c in comments:
        for line in c.split("\n"):
            line = line.strip().lstrip("/").lstrip("*").strip()
            if line:
                cleaned.append(line)
    return " ".join(cleaned) if cleaned else None


def find_identifier_calls(node, src):
    calls = set()

    def walk(n):
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                name = text(fn_node, src)
                short = name.split("::")[-1].split(".")[-1].split("->")[-1]
                calls.add(short)
        for child in n.children:
            walk(child)

    walk(node)
    return sorted(calls)


def get_declarator_name(declarator_node, src):
    node = declarator_node
    seen = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if node.type in ("identifier", "field_identifier",
                          "destructor_name", "operator_name"):
            return text(node, src)
        if node.type == "qualified_identifier":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return text(name_node, src)
        next_node = node.child_by_field_name("declarator")
        if next_node is None:
            named = [c for c in node.children if c.is_named]
            next_node = named[0] if named else None
        node = next_node
    return None


def extract_from_file(filepath):
    src = Path(filepath).read_bytes()
    tree = parser.parse(src)
    root = tree.root_node
    chunks = []

    def walk(node, namespace_stack, class_stack):
        if node.type == "namespace_definition":
            name_node = node.child_by_field_name("name")
            ns_name = text(name_node, src) if name_node else "<anonymous>"
            body = node.child_by_field_name("body")
            new_stack = namespace_stack + [ns_name]
            if body:
                for child in body.children:
                    walk(child, new_stack, class_stack)
            return

        if node.type in ("class_specifier", "struct_specifier"):
            name_node = node.child_by_field_name("name")
            cls_name = text(name_node, src) if name_node else "<anonymous>"

            parent = None
            for c in node.children:
                if c.type == "base_class_clause":
                    for sub in c.children:
                        if sub.type in ("type_identifier", "qualified_identifier"):
                            parent = text(sub, src)
                            break

            doc = get_doc_comment(node, src)
            chunks.append({
                "kind": "class" if node.type == "class_specifier" else "struct",
                "name": cls_name,
                "parent_class": parent,
                "namespace": "::".join(namespace_stack) if namespace_stack else None,
                "class": None,
                "file": Path(filepath).name,
                "signature": f"{'class' if node.type=='class_specifier' else 'struct'} {cls_name}"
                             + (f" : public {parent}" if parent else ""),
                "doc_comment": doc,
                "body": None,
                "calls": [],
            })

            body = node.child_by_field_name("body")
            new_class_stack = class_stack + [cls_name]
            if body:
                for child in body.children:
                    walk(child, namespace_stack, new_class_stack)
            return

        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            return_type_node = node.child_by_field_name("type")
            ret_type = text(return_type_node, src) if return_type_node else ""
            name = get_declarator_name(declarator, src) if declarator else None
            full_sig = text(declarator, src) if declarator else "<unknown>"
            doc = get_doc_comment(node, src)
            current_class = class_stack[-1] if class_stack else None
            body_node = node.child_by_field_name("body")
            body_text = text(body_node, src) if body_node else None
            calls = find_identifier_calls(body_node, src) if body_node else []

            chunks.append({
                "kind": "method" if current_class else "function",
                "name": name or "<unknown>",
                "parent_class": None,
                "namespace": "::".join(namespace_stack) if namespace_stack else None,
                "class": current_class,
                "file": Path(filepath).name,
                "signature": f"{ret_type} {full_sig}".strip(),
                "doc_comment": doc,
                "body": body_text,
                "calls": calls,
            })
            return

        if node.type == "declaration":
            declarator = node.child_by_field_name("declarator")
            if declarator is not None and declarator.type == "function_declarator":
                return_type_node = node.child_by_field_name("type")
                ret_type = text(return_type_node, src) if return_type_node else ""
                name = get_declarator_name(declarator, src)
                doc = get_doc_comment(node, src)
                current_class = class_stack[-1] if class_stack else None
                chunks.append({
                    "kind": "method_decl" if current_class else "function_decl",
                    "name": name or "<unknown>",
                    "parent_class": None,
                    "namespace": "::".join(namespace_stack) if namespace_stack else None,
                    "class": current_class,
                    "file": Path(filepath).name,
                    "signature": f"{ret_type} {text(declarator, src)}".strip(),
                    "doc_comment": doc,
                    "body": None,
                    "calls": [],
                })
            return

        for child in node.children:
            walk(child, namespace_stack, class_stack)

    walk(root, [], [])
    return chunks


def main(filepaths):
    all_chunks = []
    for fp in filepaths:
        all_chunks.extend(extract_from_file(fp))
    return all_chunks


if __name__ == "__main__":
    files = sys.argv[1:]
    result = main(files)
    print(json.dumps(result, indent=2))
