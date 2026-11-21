{
  "formula_i": {
    "cases": [
      {
        "f_if_mhz": 1000,
        "f_ub_mhz": 1210,
        "note": "2212/4 = 553 exact",
        "t": 203
      },
      {
        "f_if_mhz": 1001,
        "f_ub_mhz": 1210,
        "note": "2213/4 = 553.25 -> down",
        "t": 203
      },
      {
        "f_if_mhz": 1002,
        "f_ub_mhz": 1210,
        "note": "2214/4 = 553.5 -> 554 (round-half-up pin)",
        "t": 204
      },
      {
        "f_if_mhz": 1003,
        "f_ub_mhz": 1210,
        "note": "2215/4 = 553.75 -> up",
        "t": 204
      },
      {
        "f_if_mhz": 1002,
        "f_ub_mhz": 1210,
        "note": "+2 constant path (receiver tunes (t+350)*4 - f_IF ~= f_UB + 2 MHz; minisatip omits it — majority-annotated)",
        "t": 204
      },
      {
        "f_if_mhz": 1000,
        "f_ub_mhz": 1210,
        "note": "-350 bias path (round(2212/4) = 553 raw, published t = 203)",
        "t": 203
      },
      {
        "f_if_mhz": 3448,
        "f_ub_mhz": 2040,
        "note": "10-bit maximum t boundary",
        "t": 1023
      }
    ],
    "expression": "t = round((f_IF + f_UB + 2)/4) - 350",
    "protocol": "EN50494",
    "rounding": "round-half-up on the /4, integer-exact ((n + 2) // 4 form)"
  },
  "formula_ii": {
    "cases": [
      {
        "f_if_mhz": 1000,
        "t": 900
      },
      {
        "f_if_mhz": 1950,
        "t": 1850
      },
      {
        "f_if_mhz": 100,
        "note": "smallest encodable t",
        "t": 0
      },
      {
        "f_if_mhz": 2147,
        "note": "11-bit maximum t boundary",
        "t": 2047
      },
      {
        "f_if_mhz": 1100,
        "t": 1000
      },
      {
        "f_if_mhz": 1500,
        "t": 1400
      }
    ],
    "expression": "t = f_IF - 100",
    "protocol": "EN50607"
  },
  "spec_source": "SPEC-623 section 6 frequency formulas (normative; EN 50494 majority-annotated against the minisatip deviation)",
  "vector_id": "unicable-frequency-formula"
}
