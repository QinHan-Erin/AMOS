import tvm
from ...capsules import *
from ..recipe_base import (
    CompilationRecipe,
    register_recipe
)
from ..recipe_base import InstructionScope


class TenetConvBaseRecipe(CompilationRecipe):
    scope = InstructionScope.warp

    def get_name(self):
        raise NotImplementedError()

    def get_all_compute_keys(self):
        raise NotImplementedError()

    def get_all_shape_keys(self):
        raise NotImplementedError()

    def get_main_compute_expression(self, compute_key, shape_key):
        """
        ---
        Returns:
        inputs, outputs: list of tvm.te.tensor.Tensor
            the compute expression can be tracked
            through [output.op.body for output in outputs]
        """
        capsule_class = self.capsules[self.main_capsule_name]
        capsule = capsule_class(self.get_name())
        problem_size = self.get_problem_size(shape_key)
        return capsule.get_compute_expression(
            self.input_dtypes[self.main_capsule_name],
            self.output_dtypes[self.main_capsule_name],
            problem_size
        )

    def get_capsule_compute_expression(self, compute_key, shape_key, capsule_key):
        """
        ---
        Returns:
        inputs, outputs: list of tvm.te.tensor.Tensor
            the compute expression can be tracked
            through [output.op.body for output in outputs]
        """
        capsule_class = self.capsules[capsule_key]
        capsule = capsule_class(self.get_name())
        problem_size = self.get_problem_size(shape_key)
        k, p, q, c, r, s = problem_size
        A_shape = (c, p, q)
        B_shape = (k, c)
        C_shape = (k, p, q)
        if capsule_key == "cma":
            return capsule.get_compute_expression(
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        elif capsule_key == "load_image":
            return capsule.get_compute_expression(
                [A_shape],
                [A_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        elif capsule_key == "load_filter":
            return capsule.get_compute_expression(
                [B_shape],
                [B_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        elif capsule_key == "store":
            return capsule.get_compute_expression(
                [C_shape],
                [C_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        else:
            raise RuntimeError("Unknown capsule key: %s" % capsule_key)

    def get_standalone_capsule_compute_expression(self, compute_key, shape_key, capsule_key):
        return self.get_capsule_compute_expression(compute_key, shape_key, capsule_key)
    
    def get_dag_compute_expression_with_inputs(
        self, compute_key, shape_key, capsule_keys, read_graph
    ):
        """
        ---
        Returns:
        inputs, outputs: list of tvm.te.tensor.Tensor
            the compute expression can be tracked
            through [output.op.body for output in outputs]
        """
        assert len(capsule_keys) > 0
        problem_size = self.get_problem_size(shape_key)
        k, p, q, c, r, s = problem_size
        A_shape = (c, p, q)
        B_shape = (k, c)
        C_shape = (k, p, q)
        cache = {
            "a": tvm.te.placeholder(A_shape, name="A", dtype=self.input_dtypes["a"][0]),
            "b": tvm.te.placeholder(B_shape, name="B", dtype=self.input_dtypes["b"][0]),
        }
        dag_inputs = []
        dag_outputs = []

        def helper(capsule_key):
            if capsule_key in cache:
                return
            capsule_class = self.capsules[capsule_key]
            capsule = capsule_class(self.get_name())

            if capsule_key in read_graph:
                inputs = []
                for parent in read_graph[capsule_key]:
                    helper(parent)
                    assert parent in cache
                    inputs.extend(cache[parent])

                if capsule_key == "cma":
                    _, ret = capsule.get_compute_expression_with_inputs(
                        inputs,
                        self.input_dtypes[capsule_key],
                        self.output_dtypes[capsule_key],
                        problem_size
                    )
                elif capsule_key == "load_image":
                    _, ret = capsule.get_compute_expression_with_inputs(
                        inputs,
                        [A_shape],
                        [A_shape],
                        self.input_dtypes[capsule_key],
                        self.output_dtypes[capsule_key],
                        problem_size,
                    )
                elif capsule_key == "load_filter":
                    _, ret = capsule.get_compute_expression_with_inputs(
                        inputs,
                        [B_shape],
                        [B_shape],
                        self.input_dtypes[capsule_key],
                        self.output_dtypes[capsule_key],
                        problem_size,
                    )
                elif capsule_key == "store":
                    _, ret = capsule.get_compute_expression_with_inputs(
                        inputs,
                        [C_shape],
                        [C_shape],
                        self.input_dtypes[capsule_key],
                        self.output_dtypes[capsule_key],
                        problem_size,
                    )
                else:
                    raise RuntimeError("Unknown capsule key: %s" % capsule_key)
            else:
                tmp, ret = self.get_standalone_capsule_compute_expression(compute_key, shape_key, capsule_key)
                dag_inputs.extend(tmp)

            cache[capsule_key] = ret

        for capsule_key in capsule_keys:
            helper(capsule_key)
            assert capsule_key in cache
            dag_outputs.extend(cache[capsule_key])

        return dag_inputs, dag_outputs, cache

    def get_capsule_compute_expression_with_shape(
        self, compute_key, shape_key, capsule_key, input_shapes, output_shapes
    ):
        """
        ---
        Returns:
        inputs, outputs: list of tvm.te.tensor.Tensor
            the compute expression can be tracked
            through [output.op.body for output in outputs]
        """
        capsule_class = self.capsules[capsule_key]
        capsule = capsule_class(self.get_name())
        problem_size = self.get_problem_size(shape_key)
        if capsule_key == "cma":
            raise RuntimeError("Can't get expression with customized shape for main capsule.")
        elif capsule_key == "load_image":
            assert len(input_shapes) == 1
            assert len(output_shapes) == 1
            for ii, io in zip(input_shapes, output_shapes):
                assert ii == io
            return capsule.get_compute_expression(
                input_shapes,
                output_shapes,
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        elif capsule_key == "load_filter":
            assert len(input_shapes) == 1
            assert len(output_shapes) == 1
            for ii, io in zip(input_shapes, output_shapes):
                assert ii == io
            return capsule.get_compute_expression(
                input_shapes,
                output_shapes,
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        elif capsule_key == "store":
            assert len(input_shapes) == 1
            assert len(output_shapes) == 1
            for ii, io in zip(input_shapes, output_shapes):
                assert ii == io
            return capsule.get_compute_expression(
                input_shapes,
                output_shapes,
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
            )
        else:
            raise RuntimeError("Unknown capsule key: %s" % capsule_key)

    def get_problem_size(self, shape_key):
        """
        ---
        Returns:
        input_shapes, output_shapes: list of list/tuple of int
        """
        k, p, q, c, r, s = [int(x) for x in shape_key.split("x")]
        return [k, p, q, c, r, s]

    def get_intrinsic(self, compute_key, shape_key, capsule_key, **kwargs):
        """
        ---
        Returns:
        tvm.te.TensorIntrin
        """
        capsule_class = self.capsules[capsule_key]
        capsule = capsule_class(self.get_name())
        problem_size = self.get_problem_size(shape_key)
        k, p, q, c, r, s = problem_size
        A_shape = (c, p, q)
        B_shape = (k, c)
        C_shape = (k, p, q)
        if capsule_key == "load_image":
            ldm = q
            layout = "tenet::conv::chw"
            return capsule.get_intrinsic(
                [A_shape],
                [A_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
                ldm,
                layout,
                **kwargs
            )
        elif capsule_key == "load_filter":
            ldm = c
            layout = "tenet::conv::chw"
            return capsule.get_intrinsic(
                [B_shape],
                [B_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
                ldm,
                layout,
                **kwargs
            )
        elif capsule_key == "cma":
            return capsule.get_intrinsic(
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
                **kwargs
            )
        elif capsule_key == "store":
            ldm = q
            layout = "tenet::conv::mem_chw"
            return capsule.get_intrinsic(
                [C_shape],
                [C_shape],
                self.input_dtypes[capsule_key],
                self.output_dtypes[capsule_key],
                problem_size,
                ldm,
                layout,
                **kwargs
            )
        else:
            raise RuntimeError("Unknown capsule key: %s" % capsule_key)

    def get_memory_scope_realize(self, dtype, scope, constant_size, attributes):
        """
        dtype: str
            e.g. float16
        scope: str
            e.g. wmma::matrix_a
        constant_size: int
            size of elements in the buffer
        attributes: dict of {tvm.runtime.String, tvm.tir.StringImm}
            other useful information, e.g., layout/leading dimension length
        ---
        Returns:
        memory scope realization: [str, int]
            as for str, e.g. tenet::conv::fragment<
                    tenet::conv::matrix_a, 16, 16, 16,
                    tenet::conv::row_major, 16>
        """
        raise NotImplementedError()

    def get_header(self):
        return ""


@register_recipe("tenet conv", "tenet_conv_fp16_fp16")
class TenetConvFp16Fp16(TenetConvBaseRecipe):
    def __init__(self):
        self.capsules = {
            "load_image": TenetConvLoadImage,
            "load_filter": TenetConvLoadFilter,
            "cma": TenetConvCma,
            "store": TenetConvStoreImage,
        }
        self.edges = {
            "cma": ["load_image", "load_filter"],
            "store": ["cma"],
            "load_image": ["a"],
            "load_filter": ["b"],
        }
        self.main_capsule_name = "cma"
        self.anchor_point = "cma"
        self.input_dtypes = {
            "load_image": ["float16"],
            "load_filter": ["float16"],
            "cma": ["float16", "float16"],
            "store": ["float16"],
            "a": ["float16"],
            "b": ["float16"],
        }
        self.output_dtypes = {
            "load_image": ["float16"],
            "load_filter": ["float16"],
            "cma": ["float16"],
            "store": ["float16"],
            "a": ["float16"],
            "b": ["float16"],
        }

    def get_name(self):
        return "tenet_conv_fp16_fp16"

    def get_all_compute_keys(self):
        """Return all compute keys. Keys are str"""
        return ["dummy"]

    def get_all_shape_keys(self):
        """Return all shape keys. Keys are str"""
        return ["16x4x4x16x1x1"]