"""The ``Classifier`` protocol, the one interface every engine implements.

Filled at P3. Keeping this a protocol rather than a base class is what lets the
rule table, the ONNX session, and the LLM client be genuinely interchangeable.
"""
