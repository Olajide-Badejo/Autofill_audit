"""``FieldDescriptor``, ``Prediction``, and their serialisation (spec section 9.4).

Filled at P2, which defines the descriptor as the only interface between the
extractor and everything downstream. ``Prediction`` gains its shape at P3 with
the rule baseline. Both are dataclasses, never dictionaries (ground rule 9).
"""
