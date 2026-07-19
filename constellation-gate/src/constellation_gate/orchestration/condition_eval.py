from __future__ import annotations

import ast
from typing import Any

_ALLOWED_COMPARE_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.In,
    ast.NotIn,
)
_ALLOWED_BOOL_OPS = (ast.And, ast.Or)
_ALLOWED_UNARY_OPS = (ast.Not,)
_ALLOWED_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)


class SafeConditionEvaluator:
    """
    Safe boolean expression evaluator for workflow conditions.

    Available names:
    - payload
    - response
    - accumulated
    - action
    """

    def evaluate(
        self,
        expression: str,
        *,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        action: str,
        accumulated: dict[str, Any],
    ) -> bool:
        parsed = ast.parse(expression, mode="eval")
        return bool(
            self._eval(
                parsed.body,
                context={
                    "payload": payload,
                    "response": response,
                    "action": action,
                    "accumulated": accumulated,
                },
            )
        )

    def _eval(self, node: ast.AST, *, context: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ValueError(f"unknown name in condition: {node.id}")
            return context[node.id]

        if isinstance(node, ast.Expression):
            return self._eval(node.body, context=context)

        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, _ALLOWED_BOOL_OPS):
                raise ValueError("unsupported boolean operator")
            values = [bool(self._eval(value, context=context)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            return any(values)

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY_OPS):
                raise ValueError("unsupported unary operator")
            return not bool(self._eval(node.operand, context=context))

        if isinstance(node, ast.Compare):
            left = self._eval(node.left, context=context)
            result = True
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                if not isinstance(op, _ALLOWED_COMPARE_OPS):
                    raise ValueError("unsupported comparison operator")
                right = self._eval(comparator, context=context)
                result = result and self._apply_compare(op, left, right)
                left = right
            return result

        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, context=context)
            key = self._eval(node.slice, context=context)
            return value[key]

        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BIN_OPS):
                raise ValueError("unsupported binary operator")
            left = self._eval(node.left, context=context)
            right = self._eval(node.right, context=context)
            return self._apply_binop(node.op, left, right)

        if isinstance(node, ast.List):
            return [self._eval(elt, context=context) for elt in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._eval(elt, context=context) for elt in node.elts)

        if isinstance(node, ast.Dict):
            result_dict: dict[Any, Any] = {}
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:
                    raise ValueError("dict unpacking is not supported in conditions")
                result_dict[self._eval(key, context=context)] = self._eval(value, context=context)
            return result_dict

        raise ValueError(f"unsupported condition syntax: {type(node).__name__}")

    @staticmethod
    def _apply_compare(op: ast.AST, left: Any, right: Any) -> bool:
        if isinstance(op, ast.Eq):
            return bool(left == right)
        if isinstance(op, ast.NotEq):
            return bool(left != right)
        if isinstance(op, ast.Gt):
            return bool(left > right)
        if isinstance(op, ast.GtE):
            return bool(left >= right)
        if isinstance(op, ast.Lt):
            return bool(left < right)
        if isinstance(op, ast.LtE):
            return bool(left <= right)
        if isinstance(op, ast.In):
            return bool(left in right)
        if isinstance(op, ast.NotIn):
            return bool(left not in right)
        raise ValueError("unsupported comparison operator")

    @staticmethod
    def _apply_binop(op: ast.AST, left: Any, right: Any) -> Any:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        raise ValueError("unsupported binary operator")
