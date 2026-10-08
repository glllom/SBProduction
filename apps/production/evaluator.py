import ast
import operator
from typing import Dict, Any, Union

# Supported math operators
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Standard reserved math functions
_FUNCTIONS = {
    'min': min,
    'max': max,
    'round': round,
    'abs': abs,
}


class FormulaEvaluationError(Exception):
    pass


class FormulaEvaluator:
    """
    Safe mathematical expression evaluator using Python AST.
    Supported context variables:
      - Reserved geometry: H, W, thickness, etc.
      - Customizer parameters: p1, p2, p3, p4, p5
    """

    @classmethod
    def evaluate(cls, expression: Union[str, int, float], context: Dict[str, Any]) -> float:
        if isinstance(expression, (int, float)):
            return float(expression)

        if not expression or not isinstance(expression, str):
            return 0.0

        expr_str = expression.strip()
        if not expr_str:
            return 0.0

        # Quick check for pure float string
        try:
            return float(expr_str)
        except ValueError:
            pass

        try:
            tree = ast.parse(expr_str, mode='eval')
            return float(cls._eval_node(tree.body, context))
        except (FormulaEvaluationError, ZeroDivisionError, OverflowError) as e:
            raise FormulaEvaluationError(f"Error evaluating '{expression}': {str(e)}")
        except Exception as e:
            raise FormulaEvaluationError(f"Syntax error in expression '{expression}': {str(e)}")

    @classmethod
    def _eval_node(cls, node: ast.AST, context: Dict[str, Any]) -> Any:
        # Numbers: 120, 3.14
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        # Variables: H, W, p1, p2, ...
        if isinstance(node, ast.Name):
            if node.id in context:
                val = context[node.id]
                # If a nested param structure is passed, extract raw value
                if isinstance(val, dict) and 'val' in val:
                    val = val['val']
                try:
                    return float(val)
                except (ValueError, TypeError):
                    raise FormulaEvaluationError(f"Variable '{node.id}' is not a valid number: '{val}'")
            raise FormulaEvaluationError(f"Unknown variable: '{node.id}'")

        # Binary operations: A + B, A - B, A * B, A / B
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in _OPERATORS:
                left = cls._eval_node(node.left, context)
                right = cls._eval_node(node.right, context)
                return _OPERATORS[op_type](left, right)
            raise FormulaEvaluationError(f"Unsupported binary operator: {op_type.__name__}")

        # Unary operations: -A, +A
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type in _OPERATORS:
                operand = cls._eval_node(node.operand, context)
                return _OPERATORS[op_type](operand)
            raise FormulaEvaluationError(f"Unsupported unary operator: {op_type.__name__}")

        # Functions: round(H / 2), min(p1, 100)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
                func = _FUNCTIONS[node.func.id]
                args = [cls._eval_node(arg, context) for arg in node.args]
                return func(*args)
            raise FormulaEvaluationError(f"Unsupported function call")

        raise FormulaEvaluationError(f"Unsupported expression element: {type(node).__name__}")
