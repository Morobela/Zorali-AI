class GenAISpans:
    @staticmethod
    def llm_call(*args, **kwargs):
        class Dummy:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return Dummy()
