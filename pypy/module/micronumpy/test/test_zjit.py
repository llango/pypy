""" Tests that check if JIT-compiled numpy operations produce reasonably
good assembler
"""

import py
from rpython.jit.metainterp.test.support import LLJitMixin
from rpython.jit.backend.x86.test.test_basic import Jit386Mixin
from rpython.jit.metainterp.warmspot import reset_jit, get_stats
from rpython.jit.metainterp.jitprof import Profiler
from rpython.rlib.jit import Counters
from pypy.module.micronumpy import boxes
from pypy.module.micronumpy.compile import FakeSpace, Parser, InterpreterState
from pypy.module.micronumpy.base import W_NDimArray

def get_profiler():
    from rpython.jit.metainterp import pyjitpl
    return pyjitpl._warmrunnerdesc.metainterp_sd.profiler

class TestNumpyJit(Jit386Mixin):
    graph = None
    interp = None

    def setup_method(self, method):
        if not self.CPUClass.vector_extension:
            py.test.skip("needs vector extension to run (for now)")

    def assert_float_equal(self, f1, f2, delta=0.0001):
        assert abs(f1-f2) < delta

    def setup_class(cls):
        default = """
        a = [1,2,3,4]
        z = (1, 2)
        c = a + b
        sum(c) -> 1::1
        a -> 3:1:2
        """

        d = {}
        p = Parser()
        allcodes = [p.parse(default)]
        for name, meth in cls.__dict__.iteritems():
            if name.startswith("define_"):
                code = meth()
                d[name[len("define_"):]] = len(allcodes)
                allcodes.append(p.parse(code))
        cls.code_mapping = d
        cls.codes = allcodes

    def compile_graph(self):
        if self.graph is not None:
            return
        space = FakeSpace()
        codes = self.codes

        def f(i):
            interp = InterpreterState(codes[i])
            interp.run(space)
            if not len(interp.results):
                raise Exception("need results")
            w_res = interp.results[-1]
            if isinstance(w_res, W_NDimArray):
                i, s = w_res.create_iter()
                w_res = i.getitem(s)
            if isinstance(w_res, boxes.W_Float64Box):
                return w_res.value
            if isinstance(w_res, boxes.W_Float32Box):
                return float(w_res.value)
            elif isinstance(w_res, boxes.W_Int64Box):
                return float(w_res.value)
            elif isinstance(w_res, boxes.W_Int32Box):
                return float(int(w_res.value))
            elif isinstance(w_res, boxes.W_Int16Box):
                return float(int(w_res.value))
            elif isinstance(w_res, boxes.W_LongBox):
                return float(w_res.value)
            elif isinstance(w_res, boxes.W_BoolBox):
                return float(w_res.value)
            print "ERROR: did not implement return type for interpreter"
            raise TypeError(w_res)

        if self.graph is None:
            interp, graph = self.meta_interp(f, [0],
                                             listops=True,
                                             listcomp=True,
                                             backendopt=True,
                                             graph_and_interp_only=True,
                                             ProfilerClass=Profiler,
                                             vectorize=True)
            self.__class__.interp = interp
            self.__class__.graph = graph

    def check_vectorized(self, expected_tried, expected_success):
        profiler = get_profiler()
        tried = profiler.get_counter(Counters.OPT_VECTORIZE_TRY)
        success = profiler.get_counter(Counters.OPT_VECTORIZED)
        assert tried >= success
        assert tried == expected_tried
        assert success == expected_success

    def run(self, name):
        self.compile_graph()
        profiler = get_profiler()
        profiler.start()
        reset_jit()
        i = self.code_mapping[name]
        retval = self.interp.eval_graph(self.graph, [i])
        return retval

    def define_float32_copy():
        return """
        a = astype(|30|, float32)
        x1 = a -> 7
        x2 = a -> 8
        x3 = a -> 9
        x4 = a -> 10
        r = x1 + x2 + x3 + x4
        r
        """
    def test_float32_copy(self):
        result = self.run("float32_copy")
        assert int(result) == 7+8+9+10
        self.check_vectorized(1, 1)

    def define_int32_copy():
        return """
        a = astype(|30|, int32)
        x1 = a -> 7
        x2 = a -> 8
        x3 = a -> 9
        x4 = a -> 10
        x1 + x2 + x3 + x4
        """
    def test_int32_copy(self):
        result = self.run("int32_copy")
        assert int(result) == 7+8+9+10
        self.check_vectorized(1, 1)

    def define_float32_add():
        return """
        a = astype(|30|, float32)
        b = a + a
        b -> 15
        """
    def test_float32_add(self):
        result = self.run("float32_add")
        self.assert_float_equal(result, 15.0 + 15.0)
        self.check_vectorized(2, 2)

    def define_float_add():
        return """
        a = |30|
        b = a + a
        b -> 17
        """
    def test_float_add(self):
        result = self.run("float_add")
        self.assert_float_equal(result, 17.0 + 17.0)
        self.check_vectorized(1, 1)

    def define_float32_add_const():
        return """
        a = astype(|30|, float32)
        b = a + 77.345
        b -> 29
        """
    def test_float32_add_const(self):
        result = self.run("float32_add_const")
        self.assert_float_equal(result, 29.0 + 77.345)
        self.check_vectorized(2, 2)

    def define_float_add_const():
        return """
        a = |30| + 25.5
        a -> 29
        """
    def test_float_add_const(self):
        result = self.run("float_add_const")
        self.assert_float_equal(result, 29.0 + 25.5)
        self.check_vectorized(1, 1)

    def define_int_add_const():
        return """
        a = astype(|30|, int)
        b = a + 1i
        d = astype(|30|, int)
        c = d + 2.0
        x1 = b -> 7
        x2 = b -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_int_add_const(self):
        result = self.run("int_add_const")
        assert int(result) == 7+1+8+1+11+2+12+2
        self.check_vectorized(2, 2)

    def define_int32_add_const():
        return """
        a = astype(|30|, int32)
        b = a + 1i
        d = astype(|30|, int32)
        c = d + 2.0
        x1 = b -> 7
        x2 = b -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_int32_add_const(self):
        result = self.run("int32_add_const")
        assert int(result) == 7+1+8+1+11+2+12+2
        self.check_vectorized(2, 2)

    def define_int_mul_array():
        return """
        a = astype(|30|, int)
        b = astype(|30|, int)
        c = a * b
        x1 = c -> 7
        x2 = c -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_int_mul_array(self):
        py.test.skip("how to multiply quad word integers?")
        result = self.run("int_mul_array")
        assert int(result) == 7*7+8*8+11*11+12*12
        self.check_vectorized(2, 2)

    def define_float_mul_array():
        return """
        a = astype(|30|, float)
        b = astype(|30|, float)
        c = a * b
        x1 = c -> 7
        x2 = c -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_float_mul_array(self):
        result = self.run("float_mul_array")
        assert int(result) == 7*7+8*8+11*11+12*12
        self.check_vectorized(2, 2)

    def define_int32_mul_array():
        return """
        a = astype(|30|, int32)
        b = astype(|30|, int32)
        c = a * b
        x1 = c -> 7
        x2 = c -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_int32_mul_array(self):
        result = self.run("int32_mul_array")
        assert int(result) == 7*7+8*8+11*11+12*12
        self.check_vectorized(2, 2)

    def define_float32_mul_array():
        return """
        a = astype(|30|, float32)
        b = astype(|30|, float32)
        c = a * b
        x1 = c -> 7
        x2 = c -> 8
        x3 = c -> 11
        x4 = c -> 12
        x1 + x2 + x3 + x4
        """
    def test_float32_mul_array(self):
        result = self.run("float32_mul_array")
        assert int(result) == 7*7+8*8+11*11+12*12
        self.check_vectorized(2, 2)

    def define_pow():
        return """
        a = |30| ** 2
        a -> 29
        """

    def test_pow(self):
        py.test.skip("Not implemented CDefinedIntSymbolic('RPY_TLOFS_rpy_errno')")
        result = self.run("pow")
        assert result == 29 ** 2
        self.check_trace_count(1)

    def define_pow_int():
        return """
        a = astype(|30|, int)
        b = astype([2], int)
        c = a ** b
        c -> 15 
        """

    def test_pow_int(self):
        py.test.skip("Not implemented CDefinedIntSymbolic('RPY_TLOFS_rpy_errno')")
        result = self.run("pow_int")
        assert result == 15 ** 2
        self.check_trace_count(4)  # extra one for the astype

    def define_sum():
        return """
        a = |30|
        sum(a)
        """

    def test_sum(self):
        result = self.run("sum")
        assert result == sum(range(30))
        self.check_trace_count(1)

    def define_cumsum():
        return """
        a = |30|
        b = cumsum(a)
        b -> 5
        """

    def test_cumsum(self):
        result = self.run("cumsum")
        assert result == 15
        self.check_trace_count(1)

    def define_axissum():
        return """
        a = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]
        b = sum(a,0)
        b -> 1
        """

    def test_axissum(self):
        result = self.run("axissum")
        assert result == 30
        # XXX note - the bridge here is fairly crucial and yet it's pretty
        #            bogus. We need to improve the situation somehow.

    def define_reduce():
        return """
        a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        sum(a)
        """

    def test_reduce_compile_only_once(self):
        py.test.skip('TODO')
        self.compile_graph()
        reset_jit()
        i = self.code_mapping['reduce']
        # run it twice
        retval = self.interp.eval_graph(self.graph, [i])
        retval = self.interp.eval_graph(self.graph, [i])
        # check that we got only one loop
        assert len(get_stats().loops) == 1

    def test_reduce_axis_compile_only_once(self):
        py.test.skip('TODO')
        self.compile_graph()
        reset_jit()
        i = self.code_mapping['axissum']
        # run it twice
        retval = self.interp.eval_graph(self.graph, [i])
        retval = self.interp.eval_graph(self.graph, [i])
        # check that we got only one loop
        assert len(get_stats().loops) == 1

    def define_prod():
        return """
        a = |30|
        prod(a)
        """

    def test_prod(self):
        py.test.skip('TODO')
        result = self.run("prod")
        expected = 1
        for i in range(30):
            expected *= i * 2
        assert result == expected
        self.check_trace_count(1)
        self.check_simple_loop({
            'float_mul': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'int_add': 2,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 1,
        })

    def define_max():
        return """
        a = |30|
        a[13] = 128
        max(a)
        """

    def test_max(self):
        py.test.skip('TODO')
        result = self.run("max")
        assert result == 128
        self.check_trace_count(3)
        self.check_simple_loop({
            'float_ge': 1,
            'float_ne': 1,
            'guard_false': 3,
            'guard_not_invalidated': 1,
            'int_add': 2,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 1,
        })
        self.check_resops({
            'float_ge': 2,
            'float_ne': 2,
            'getfield_gc': 4,
            'getfield_gc_pure': 30,
            'guard_class': 1,
            'guard_false': 8,
            'guard_nonnull': 2,
            'guard_nonnull_class': 2,
            'guard_not_invalidated': 2,
            'guard_true': 7,
            'guard_value': 2,
            'int_add': 8,
            'int_ge': 4,
            'int_is_true': 3,
            'jump': 3,
            'raw_load': 2,
        })

    def define_min():
        return """
        a = |30|
        a[13] = -128
        min(a)
        """

    def test_min(self):
        py.test.skip('TODO')
        result = self.run("min")
        assert result == -128
        self.check_trace_count(1)
        self.check_simple_loop({
            'float_le': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 1,
            'int_add': 2,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 1,
        })

    def define_any():
        return """
        a = [0,0,0,0,0,0,0,1,0,0,0]
        any(a)
        """

    def test_any(self):
        result = self.run("any")
        assert result == 1
        self.check_trace_count(1)

    def define_all():
        return """
        a = [1,1,1,1,1,1,1,1]
        all(a)
        """

    def test_all(self):
        result = self.run("all")
        assert result == 1
        self.check_trace_count(1)

    def define_logical_xor_reduce():
        return """
        a = [1,1,1,1,1,1,1,1]
        logical_xor_reduce(a)
        """

    def test_logical_xor_reduce(self):
        py.test.skip('TODO')
        result = self.run("logical_xor_reduce")
        assert result == 0
        self.check_trace_count(2)
        # XXX fix this
        self.check_simple_loop({
            'cast_float_to_int': 1,
            'getfield_gc': 2,
            'getfield_gc_pure': 11,
            'guard_class': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 5,
            'int_add': 2,
            'int_and': 1,
            'int_ge': 1,
            'int_is_true': 2,
            'jump': 1,
            'new_with_vtable': 1,
            'raw_load': 1,
            'setfield_gc': 4,
        })

    def define_already_forced():
        return """
        a = |30|
        b = a + 4.5
        b -> 5 # forces
        c = b * 8
        c -> 5
        """

    def test_already_forced(self):
        py.test.skip('TODO')
        result = self.run("already_forced")
        assert result == (5 + 4.5) * 8
        # This is the sum of the ops for both loops, however if you remove the
        # optimization then you end up with 2 float_adds, so we can still be
        # sure it was optimized correctly.
        py.test.skip("too fragile")
        self.check_resops({'raw_store': 4, 'getfield_gc': 22,
                           'getarrayitem_gc': 4, 'getarrayitem_gc_pure': 2,
                           'getfield_gc_pure': 8,
                           'guard_class': 8, 'int_add': 8, 'float_mul': 2,
                           'jump': 2, 'int_ge': 4,
                           'raw_load': 4, 'float_add': 2,
                           'guard_false': 4, 'arraylen_gc': 2, 'same_as': 2})

    def define_ufunc():
        return """
        a = |30|
        b = unegative(a)
        b -> 3
        """

    def test_ufunc(self):
        py.test.skip('TODO')
        result = self.run("ufunc")
        assert result == -3
        self.check_simple_loop({
            'float_neg': 1,
            'guard_not_invalidated': 1,
            'int_add': 3,
            'int_ge': 1,
            'guard_false': 1,
            'jump': 1,
            'raw_load': 1,
            'raw_store': 1,
        })

    def define_specialization():
        return """
        a = |30|
        b = a + a
        c = unegative(b)
        c -> 3
        d = a * a
        unegative(d)
        d -> 3
        d = a * a
        unegative(d)
        d -> 3
        d = a * a
        unegative(d)
        d -> 3
        d = a * a
        unegative(d)
        d -> 3
        """

    def test_specialization(self):
        py.test.skip('TODO')
        self.run("specialization")
        py.test.skip("don't run for now")
        # This is 3, not 2 because there is a bridge for the exit.
        self.check_trace_count(3)

    def define_slice():
        return """
        a = |30|
        b = a -> ::3
        c = b + b
        c -> 3
        """

    def test_slice(self):
        py.test.skip('TODO')
        result = self.run("slice")
        assert result == 18
        self.check_trace_count(1)
        self.check_simple_loop({
            'arraylen_gc': 2,
            'float_add': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'int_add': 4,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
        })

    def define_take():
        return """
        a = |10|
        b = take(a, [1, 1, 3, 2])
        b -> 2
        """

    def test_take(self):
        py.test.skip('TODO')
        skip('"take" not implmenented yet')
        result = self.run("take")
        assert result == 3
        self.check_simple_loop({'raw_load': 2,
                                'cast_float_to_int': 1,
                                'int_lt': 1,
                                'int_ge': 2,
                                'guard_false': 3,
                                'raw_store': 1,
                                'int_mul': 1,
                                'int_add': 3,
                                'jump': 1,
                                'arraylen_gc': 2})

    def define_multidim():
        return """
        a = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]
        b = a + a
        b -> 1 -> 1
        """

    def test_multidim(self):
        py.test.skip('TODO')
        result = self.run('multidim')
        assert result == 8
        # int_add might be 1 here if we try slightly harder with
        # reusing indexes or some optimization
        self.check_trace_count(1)
        self.check_simple_loop({
            'float_add': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'int_add': 4,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
        })

    def define_multidim_slice():
        return """
        a = [[1, 2, 3, 4], [3, 4, 5, 6], [5, 6, 7, 8], [7, 8, 9, 10], [9, 10, 11, 12], [11, 12, 13, 14], [13, 14, 15, 16], [16, 17, 18, 19]]
        b = a -> ::2
        c = b + b
        c -> 1 -> 1
        """

    def test_multidim_slice(self):
        py.test.skip('TODO')
        result = self.run('multidim_slice')
        assert result == 12
        # XXX the bridge here is scary. Hopefully jit-targets will fix that,
        #     otherwise it looks kind of good
        self.check_trace_count(2)
        self.check_simple_loop({
            'float_add': 1,
            'getarrayitem_gc': 2,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 2,
            'int_add': 6,
            'int_ge': 1,
            'int_lt': 2,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
            'setarrayitem_gc': 2,
        })
        self.check_resops({
            'float_add': 3,
            'getarrayitem_gc': 7,
            'getarrayitem_gc_pure': 14,
            'getfield_gc': 6,
            'getfield_gc_pure': 63,
            'guard_class': 5,
            'guard_false': 19,
            'guard_nonnull': 6,
            'guard_nonnull_class': 1,
            'guard_not_invalidated': 3,
            'guard_true': 16,
            'guard_value': 3,
            'int_add': 24,
            'int_ge': 4,
            'int_is_true': 5,
            'int_is_zero': 4,
            'int_le': 5,
            'int_lt': 7,
            'int_sub': 2,
            'jump': 2,
            'raw_load': 5,
            'raw_store': 3,
            'setarrayitem_gc': 8,
        })

    def define_broadcast():
        return """
        a = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
        b = [1, 2, 3, 4]
        c = a + b
        c -> 1 -> 2
        """

    def test_broadcast(self):
        py.test.skip('TODO')
        result = self.run("broadcast")
        assert result == 10
        self.check_trace_count(2)
        self.check_simple_loop({
            'float_add': 1,
            'getarrayitem_gc': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 1,
            'int_add': 5,
            'int_ge': 1,
            'int_lt': 1,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
            'setarrayitem_gc': 1,
        })
        self.check_resops({
            'float_add': 2,
            'getarrayitem_gc': 2,
            'getarrayitem_gc_pure': 2,
            'getfield_gc': 6,
            'getfield_gc_pure': 30,
            'guard_class': 3,
            'guard_false': 7,
            'guard_nonnull': 2,
            'guard_not_invalidated': 2,
            'guard_true': 8,
            'int_add': 11,
            'int_ge': 2,
            'int_is_true': 3,
            'int_is_zero': 1,
            'int_le': 1,
            'int_lt': 2,
            'jump': 1,
            'raw_load': 4,
            'raw_store': 2,
            'setarrayitem_gc': 2,
        })

    def define_setslice():
        return """
        a = |30|
        b = |10|
        b[1] = 5.5
        a[0:30:3] = b
        a -> 3
        """

    def test_setslice(self):
        py.test.skip('TODO')
        result = self.run("setslice")
        assert result == 5.5
        self.check_trace_count(1)
        self.check_simple_loop({
            'arraylen_gc': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'int_add': 3,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 1,
            'raw_store': 1,
        })

    def define_virtual_slice():
        return """
        a = |30|
        c = a + a
        d = c -> 1:20
        d -> 1
        """

    def test_virtual_slice(self):
        py.test.skip('TODO')
        result = self.run("virtual_slice")
        assert result == 4
        py.test.skip("don't run for now")
        self.check_trace_count(1)
        self.check_simple_loop({'raw_load': 2, 'float_add': 1,
                                'raw_store': 1, 'int_add': 1,
                                'int_ge': 1, 'guard_false': 1, 'jump': 1,
                                'arraylen_gc': 1})

    def define_flat_iter():
        return '''
        a = |30|
        b = flat(a)
        c = b + a
        c -> 3
        '''

    def test_flat_iter(self):
        py.test.skip('TODO')
        result = self.run("flat_iter")
        assert result == 6
        self.check_trace_count(1)
        self.check_simple_loop({
            'float_add': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'int_add': 4,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
        })

    def define_flat_getitem():
        return '''
        a = |30|
        b = flat(a)
        b -> 4: -> 6
        '''

    def test_flat_getitem(self):
        py.test.skip('TODO')
        result = self.run("flat_getitem")
        assert result == 10.0
        self.check_trace_count(1)
        self.check_simple_loop({
            'guard_false': 1,
            'int_add': 4,
            'int_ge': 1,
            'int_mul': 1,
            'jump': 1,
            'raw_load': 1,
            'raw_store': 1,
        })

    def define_flat_setitem():
        return '''
        a = |30|
        b = flat(a)
        b[4:] = a->:26
        a -> 5
        '''

    def test_flat_setitem(self):
        py.test.skip('TODO')
        result = self.run("flat_setitem")
        assert result == 1.0
        self.check_trace_count(1)
        self.check_simple_loop({
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 1,
            'int_add': 4,
            'int_ge': 1,
            'int_gt': 1,
            'int_mul': 1,
            'int_sub': 1,
            'jump': 1,
            'raw_load': 1,
            'raw_store': 1,
        })

    def define_dot():
        return """
        a = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
        b = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]
        c = dot(a, b)
        c -> 1 -> 2
        """

    def test_dot(self):
        py.test.skip('TODO')
        result = self.run("dot")
        assert result == 184
        self.check_trace_count(3)
        self.check_simple_loop({
            'float_add': 1,
            'float_mul': 1,
            'guard_not_invalidated': 1,
            'guard_true': 1,
            'int_add': 3,
            'int_lt': 1,
            'jump': 1,
            'raw_load': 2,
        })
        self.check_resops({
            'float_add': 2,
            'float_mul': 2,
            'getarrayitem_gc': 4,
            'getarrayitem_gc_pure': 9,
            'getfield_gc': 7,
            'getfield_gc_pure': 42,
            'guard_class': 4,
            'guard_false': 15,
            'guard_not_invalidated': 2,
            'guard_true': 14,
            'int_add': 17,
            'int_ge': 4,
            'int_is_true': 3,
            'int_is_zero': 2,
            'int_le': 5,
            'int_lt': 8,
            'int_sub': 3,
            'jump': 3,
            'new_with_vtable': 7,
            'raw_load': 6,
            'raw_store': 1,
            'same_as': 2,
            'setarrayitem_gc': 7,
            'setfield_gc': 22,
        })

    def define_argsort():
        return """
        a = |30|
        argsort(a)
        a->6
        """

    def test_argsort(self):
        py.test.skip('TODO')
        result = self.run("argsort")
        assert result == 6

    def define_where():
        return """
        a = [1, 0, 1, 0]
        x = [1, 2, 3, 4]
        y = [-10, -20, -30, -40]
        r = where(a, x, y)
        r -> 3
        """

    def test_where(self):
        py.test.skip('TODO')
        result = self.run("where")
        assert result == -40
        self.check_trace_count(1)
        self.check_simple_loop({
            'float_ne': 1,
            'guard_false': 1,
            'guard_not_invalidated': 1,
            'guard_true': 1,
            'int_add': 5,
            'int_ge': 1,
            'jump': 1,
            'raw_load': 2,
            'raw_store': 1,
        })

    def define_searchsorted():
        return """
        a = [1, 4, 5, 6, 9]
        b = |30| -> ::-1
        c = searchsorted(a, b)
        c -> -1
        """

    def test_searchsorted(self):
        py.test.skip('TODO')
        result = self.run("searchsorted")
        assert result == 0
        self.check_trace_count(6)
        self.check_simple_loop({
            'float_lt': 1,
            'guard_false': 2,
            'guard_not_invalidated': 1,
            'guard_true': 2,
            'int_add': 3,
            'int_ge': 1,
            'int_lt': 2,
            'int_mul': 1,
            'int_rshift': 1,
            'int_sub': 1,
            'jump': 1,
            'raw_load': 1,
        })
