"""Studio FastAPI service.

The service is a thin layer over the StudioStore + the Elenchus library.
Per Rule 7, it calls elenchus.verifier.Verifier through its public API;
it does not reach into private internals. Per Rule 6, soteria/lethe
integration is OUT of this package — that file lives in
studio/integrations/ and is only added when the user supplies source.

The Verifier is built per-request via an injected factory so the test
suite can use a stub NLI without booting the real model.
"""
