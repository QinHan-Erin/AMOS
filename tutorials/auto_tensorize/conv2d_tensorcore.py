import tvm
import numpy as np


# The sizes of WMMA
WMMA_M = 16
WMMA_N = 16
WMMA_K = 16

# The sizes of inputs and filters
batch_size = 256
height = 14
width = 14
in_channels = 256
out_channels = 512
kernel_h = 3
kernel_w = 3
pad_h = 1
pad_w = 1
stride_h = 1
stride_w = 1


def conv2d_nchw(N, C, H, W, K, R, S,
                stride=1, padding=0, dilation=1,
                dtype="float16", out_dtype="float32"):
    Src = tvm.te.placeholder([N, C, H, W], name="Src", dtype=dtype)
    Filter = tvm.te.placeholder([K, C, R, S], name="Filter", dtype=dtype)

    Padded = tvm.te.compute(
        [N, C, H+2*padding, W+2*padding],
        lambda n, c, h, w: tvm.tir.if_then_else(
            tvm.tir.all(
                h >= padding, h + padding < H, w >= padding, w + padding < W),
            Src[n, c, h - padding, w - padding],
            tvm.tir.const(0.0, dtype)
        ),
        name="Padded"
    )

    kh = (R - 1) * dilation + 1
    kw = (S - 1) * dilation + 1
    P = (H + 2 * padding - kh) // stride + 1
    Q = (W + 2 * padding - kw) // stride + 1

    rr = tvm.te.reduce_axis([0, R], name="rr")
    rs = tvm.te.reduce_axis([0, S], name="rs")
    rc = tvm.te.reduce_axis([0, C], name="rc")

    Output = tvm.te.compute(
        [N, K, P, Q],
        lambda n, k, p, q: tvm.te.sum(
            Padded[n, rc, p*stride + rr*dilation, q*stride + rr*dilation]
            * Filter[k, rc, rr, rs],
            axis=[rr, rs, rc]
        ),
        name="Output"
    )

    return Output, [Src, Filter, Output]


def conv2d_nchwnc(N, C, H, W, K, R, S, NI, CI, KI,
                  stride=1, padding=0, dilation=1,
                  dtype="float16", out_dtype="float32"):
    assert (N % NI == 0) and (C % CI == 0) and (K % KI == 0)
    NO, CO, KO = N // NI, C // CI, K // KI
    Src = tvm.te.placeholder([NO, CO, H, W, NI, CI], name="Src", dtype=dtype)
    Filter = tvm.te.placeholder(
        [KO, CO, R, S, KI, CI],
        name="Filter",
        dtype=dtype
    )

    Padded = tvm.te.compute(
        [NO, CO, H+2*padding, W+2*padding, NI, CI],
        lambda n, c, h, w, nn, cc:
            tvm.tir.if_then_else(
                tvm.tir.all(
                    h >= padding,
                    h + padding < H,
                    w >= padding,
                    w + padding < W
                ),
                Src[n, c, h - padding, w - padding, nn, cc],
                tvm.tir.const(0.0, dtype)
            ),
        name="Padded"
    )

    kh = (R - 1) * dilation + 1
    kw = (S - 1) * dilation + 1
    P = (H + 2 * padding - kh) // stride + 1
    Q = (W + 2 * padding - kw) // stride + 1

    rr = tvm.te.reduce_axis([0, R], name="rr")
    rs = tvm.te.reduce_axis([0, S], name="rs")
    rco = tvm.te.reduce_axis([0, CO], name="rco")
    rci = tvm.te.reduce_axis([0, CI], name="rci")

    Output = tvm.te.compute(
        [NO, KO, P, Q, NI, KI],
        lambda n, k, p, q, nn, kk:
            tvm.te.sum(
                Padded[n, rco, p*stride+rr*dilation,
                       q*stride+rs*dilation, nn, rci]
                * Filter[k, rco, rr, rs, kk, rci]
            ),
        name="Output"
    )

    return Output, [Src, Filter, Output]


def conv2d_intrin_wmma_load_matrix(strides_from, operand="Src",
                                   dtype="float16", layout="NCHW"):
    layout = layout.upper()
    assert operand in ["Src", "Filter"]
    assert dtype in ["int4", "int8", "float16"]
    if layout == "NCHW":
        assert isinstance(strides_from, list) and len(strides_from) == 4
        assert strides_from[1] == 1
        if operand == "Src":
            A = tvm.te.placeholder(
                [WMMA_M, WMMA_K, 1, 1], dtype=dtype, name="A")
            bA = tvm.tir.decl_buffer(
                A.shape,
                A.dtype,
                scope="shared",
                strides=strides_from,
                data_alignment=WMMA_K * (
                                    tvm.runtime.DataType(dtype).bits // 8),
                offset_factor=WMMA_K)
            C = tvm.te.compute(
                [WMMA_M, WMMA_K, 1, 1],
                lambda i, j, p, q: A[i, j, p, q], name="C")
            bC = tvm.tir.decl_buffer(
                C.shape,
                C.dtype,
                scope="wmma.matrix_a",
                data_alignment=WMMA_K * (
                                    tvm.runtime.DataType(dtype).bits // 8),
                offset_factor=WMMA_K)

            def intrin_func(ins, outs):
                ib = tvm.tir.ir_builder.create()

                BA = ins[0]
                BC = outs[0]
                ib.emit(
                    tvm.tir.call_intrin(
                        "handle",
                        "tir.tvm_load_matrix_sync",
                        BC.data,
                        WMMA_M, 
                        WMMA_N,
                        WMMA_K,
                        BC.elem_offset // (WMMA_M * WMMA_K),
                        BA.access_ptr("r"),
                        strides_from[0],
                        "row_major"
                    )
                )
                return ib.get()

            return tvm.te.decl_tensor_intrin(
                C.op, intrin_func, binds={A: bA, C: bC})
        elif operand == "Filter":
            A = tvm.te.placeholder(
                [WMMA_N, WMMA_K, 1, 1], dtype=dtype, name="A")
            bA = tvm.tir.decl_buffer(
                A.shape,
                A.dtype,
                scope="shared",
                strides=strides_from,
                data_alignment=WMMA_K * (
                                    tvm.runtime.DataType(dtype).bits // 8),
                offset_factor=WMMA_K)
            C = tvm.te.compute(
                [WMMA_N, WMMA_K, 1, 1],
                lambda i, j, p, q: A[i, j, p, q], name="C")
            bC = tvm.tir.decl_buffer(
                C.shape,
                C.dtype,
                scope="wmma.matrix_b",
                data_alignment=WMMA_K * (
                                    tvm.runtime.DataType(dtype).bits // 8),
                offset_factor=WMMA_K)

            def intrin_func(ins, outs):
                ib = tvm.tir.ir_builder.create()
                BA = ins[0]
                BC = outs[0]
                ib.emit(
                    tvm.tir.call_intrin(
                        "handle",
                        "tir.tvm_load_matrix_sync",
                        BC.data,
                        WMMA_M, 
                        WMMA_N,
                        WMMA_K,
                        BC.elem_offset // (WMMA_N * WMMA_K),
                        BA.access_ptr("r"),
                        strides_from[0],
                        "col_major"
                    )
                )
                return ib.get()

            return tvm.te.decl_tensor_intrin(
                C.op, intrin_func, binds={A: bA, C: bC})
        else:
            raise RuntimeError("Unknown operand: %s" % operand)
    else:
        raise RuntimeError("Unknown layout: %s" % layout)


def conv2d_intrin_wmma_store_matrix(
        strides_dst, dtype="float16", out_dtype="float32", layout="NCHW"):
    layout = layout.upper()
    assert dtype in ["int4", "int8", "float16"]
    assert out_dtype in ["int32", "float32"]
    if layout == "NCHW":
        assert isinstance(strides_dst, list) and len(strides_dst) == 4
        assert strides_dst[1] == 1
        A = tvm.te.placeholder(
            [WMMA_M, WMMA_N, 1, 1], dtype=dtype, name="A")
        bA = tvm.tir.decl_buffer(
            A.shape,
            A.dtype,
            scope="wmma.accumulator",
            data_alignment=WMMA_N * (
                                tvm.runtime.DataType(dtype).bits // 8),
            offset_factor=WMMA_N)
        C = tvm.te.compute(
            [WMMA_M, WMMA_N, 1, 1],
            lambda i, j, p, q: A[i, j, p, q].astype(out_dtype), name="C")
        bC = tvm.tir.decl_buffer(
            C.shape,
            C.dtype,
            scope="local",
            data_alignment=WMMA_N * (
                                tvm.runtime.DataType(dtype).bits // 8),
            offset_factor=WMMA_N)

        def intrin_func(ins, outs):
            ib = tvm.tir.ir_builder.create()

            BA = ins[0]
            BC = outs[0]
            ib.emit(
                tvm.tir.call_intrin(
                    "handle",
                    "tir.tvm_store_matrix_sync",
                    BA.data,
                    WMMA_M, 
                    WMMA_N,
                    WMMA_K,
                    BA.elem_offset // (WMMA_M * WMMA_K),
                    BC.access_ptr("w"),
                    strides_dst[0],
                    "row_major"
                )
            )
            return ib.get()

        return tvm.te.decl_tensor_intrin(
            C.op, intrin_func, binds={A: bA, C: bC})
    else:
        raise RuntimeError("Unknown layout: %s" % layout)


def conv2d_intrin_wmma_mma_sync(
        dtype="float16", out_dtype="float32", layout="NCHW"):
    layout = layout.upper()
    assert dtype in ["int4", "int8", "float16"]
    assert out_dtype in ["int32", "float32"]
    if layout == "NCHW":
        A = tvm.te.placeholder((WMMA_M, WMMA_K), name="A", dtype=dtype)
        B = tvm.te.placeholder((WMMA_N, WMMA_K), name="B", dtype=dtype)
        k = tvm.te.reduce_axis((0, WMMA_K), name="k")
        C = tvm.te.compute(
            (WMMA_M, WMMA_N),
            lambda ii, jj: tvm.te.sum(
                A[ii, k].astype(out_dtype) * B[k, jj].astype(out_dtype),
                axis=k),
            name="C",
        )
        bA = tvm.tir.decl_buffer(
            A.shape, A.dtype,
            name="BA", scope="wmma.matrix_a",
            data_alignment=WMMA_K * (tvm.runtime.DataType(dtype).bits // 8),
            offset_factor=WMMA_M * WMMA_K
        )
        bB = tvm.tir.decl_buffer(
            B.shape, B.dtype,
            name="BA", scope="wmma.matrix_b",
            data_alignment=WMMA_K * (tvm.runtime.DataType(dtype).bits // 8),
            offset_factor=WMMA_N * WMMA_K
        )
        bC = tvm.tir.decl_buffer(
            A.shape, A.dtype,
            name="BA", scope="wmma.accumulator",
            data_alignment=WMMA_N * (tvm.runtime.DataType(dtype).bits // 8),
            offset_factor=WMMA_M * WMMA_N
        )

        def intrin_func(ins, outs):
            BA, BB = ins
            BC, = outs

            def init():
                ib = tvm.tir.ir_builder.create()
                ib.emit(
                    tvm.tir.call_intrin(
                        "handle", "tir.tvm_fill_fragment",
                        BC.data, WMMA_M, WMMA_N, WMMA_K,
                        BC.elem_offset // (WMMA_M * WMMA_N), 0.0
                    )
                )
                return ib.get()

            def update():
                ib = tvm.tir.ir_builder.create()
                ib.emit(
                    tvm.tir.call_intrin(
                        "handle",
                        "tir.tvm_mma_sync",
                        BC.data,
                        BC.elem_offset // (WMMA_M * WMMA_N),
                        BA.data,
                        BA.elem_offset // (WMMA_M * WMMA_K),
                        BB.data,
                        BB.elem_offset // (WMMA_N * WMMA_K),
                        BC.data,
                        BC.elem_offset // (WMMA_M * WMMA_N),
                    )
                )
                return ib.get()

            return update(), init(), update()

        return tvm.te.decl_tensor_intrin(
            C.op, intrin_func, binds={A: bA, B: bB, C: bC})
    else:
        raise RuntimeError("Unknown layout: %s" % layout)


def schedule_conv2d_nchw(args):
    Src, Filter, Output = args
    Padded = Output.op.input_tensors[0]

    sch = tvm.te.create_schedule(Output.op)
    sch[Padded].compute_inline()

    AS = sch.cache_read(Padded, "shared", [Output])
    WS = sch.cache_read(Filter, "shared", [Output])
    AL = sch.cache_read(AS, "wmma.matrix_a", [Output])
    WL = sch.cache_read(WS, "wmma.matrix_b", [Output])
    OL = sch.cache_write(Output, "wmma.accumulator")
    OLL = sch.cache_read(OL, "local", [Output])

    NO = 4
    NV = 2
    NT = 2
    NI = WMMA_M
    assert (NO * NV * NT * NI) == batch_size
    KO = 4
    KV = 2
    KT = 4
    KI = WMMA_N
    assert (KO * KV * KT * KI) == out_channels
    CO = 4
    CV = 4
    CI = WMMA_K
    assert (CO * CV * CI) == in_channels

    block_x = tvm.te.thread_axis("blockIdx.x")
    block_y = tvm.te.thread_axis("blockIdx.y")
    block_z = tvm.te.thread_axis("blockIdx.z")
    thread_vx = tvm.te.thread_axis("vthread")
    thread_vy = tvm.te.thread_axis("vthread")
    thread_vz = tvm.te.thread_axis("vthread")
    thread_x = tvm.te.thread_axis("threadIdx.x")
    thread_y = tvm.te.thread_axis("threadIdx.y")
    thread_z = tvm.te.thread_axis("threadIdx.z")

    # schedule output
    n, k, p, q = sch[Output].op.axis
    no, n = sch[Output].split(n, nparts=NO)
    nv, n = sch[Output].split(n, nparts=NV)
    nt, ni = sch[Output].split(n, nparts=NT)
    ko, k = sch[Output].split(k, nparts=KO)
    kv, k = sch[Output].split(k, nparts=KV)
    kt, ki = sch[Output].split(k, nparts=KT)
    pq = sch[Output].fuse(p, q)
    sch[Output].reorder(pq, no, ko, nv, kv, nt, kt, ni, ki)
    sch[Output].bind(pq, block_x)
    sch[Output].bind(no, block_z)
    sch[Output].bind(ko, block_y)
    # sch[Output].bind(nv, thread_vz)
    # sch[Output].bind(kv, thread_vy)
    sch[Output].bind(nt, thread_z)
    sch[Output].bind(kt, thread_y)

    # schedule local
    sch[OL].compute_at(sch[Output], kt)
    n, k, p, q = sch[OL].op.axis
    rr, rs, rc = sch[OL].op.reduce_axis
    rco, rc = sch[OL].split(rc, nparts=CO)
    rcv, rci = sch[OL].split(rc, nparts=CV)
    sch[OL].reorder(rco, rr, rs, rcv, n, k, rci)

    sch[OLL].compute_at(sch[Output], kt)

    # fragment memory
    sch[AL].compute_at(sch[OL], rcv)
    sch[WL].compute_at(sch[OL], rcv)

    # schedule for Src's shared memory
    sch[AS].compute_at(sch[OL], rs)
    n, c, h, w = sch[AS].op.axis
    no, n = sch[AS].split(n, nparts=NT)
    nv, ni = sch[AS].split(n, nparts=KT)
    co, ci = sch[AS].split(c, nparts=2)
    sch[AS].reorder(h, w, no, co, nv, ni, ci)
    sch[AS].bind(no, thread_z)
    sch[AS].bind(nv, thread_y)
    sch[AS].bind(co, thread_x)

    # schedule for Filter's shared memory
    sch[WS].compute_at(sch[OL], rs)
    k, c, r, s = sch[WS].op.axis
    ko, k = sch[WS].split(k, nparts=NT)
    kv, ki = sch[WS].split(k, nparts=KT)
    co, ci = sch[WS].split(c, nparts=2)
    sch[WS].reorder(r, s, ko, co, kv, ki, ci)
    sch[WS].bind(ko, thread_z)
    sch[WS].bind(kv, thread_y)
    sch[WS].bind(co, thread_x)

    # tensorize
    sch[AL].tensorize(sch[AL].op.axis[0], conv2d_intrin_wmma_load_matrix(
        [CV * CI, 1, 1, 1],
        operand="Src",
        dtype="float16",
        layout="NCHW"
    ))
    sch[WL].tensorize(sch[WL].op.axis[0], conv2d_intrin_wmma_load_matrix(
        [CV * CI, 1, 1, 1],
        operand="Filter",
        dtype="float16",
        layout="NCHW"
    ))
    sch[OLL].tensorize(sch[OLL].op.axis[0], conv2d_intrin_wmma_store_matrix(
        [KI, 1, 1, 1],
        dtype="float32",
        layout="NCHW"
    ))
    

    print(tvm.lower(sch, args, simple_mode=True))


def schedule_conv2d_nchwnc(args):
    Src, Filter, Output = args
    Padded = Output.op.input_tensors[0]

    s = tvm.te.create_schedule(Output.op)
    s[Padded].compute_inline()

    AS = s.cache_read(Padded, "shared", [Output])
    WS = s.cache_read(Filter, "shared", [Output])
    AL = s.cache_read(AS, "wmma.matrix_a", [Output])
    WL = s.cache_read(WS, "wmma.matrix_b", [Output])
    OL = s.cache_write(Output, "wmma.accumulator")
    pass


if __name__ == "__main__":
    output, args = conv2d_nchw(
        batch_size,
        in_channels,
        height,
        width,
        out_channels,
        kernel_h,
        kernel_w,
        stride=stride_h,
        padding=pad_h,
        dilation=1,
        dtype="float16",
        out_dtype="float32")
    schedule_conv2d_nchw(args)
