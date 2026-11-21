{
  "bit_conventions": "data1 EN50494 [UB:7-5|position:4|polarization:3|band:2|t:1-0] MSB-first; polarization 0=vertical/1=horizontal; band 0=low/1=high (universal boundary 11700000 kHz); position 0=A/1=B; EN50607 data1 bit7-3=UB, data1 bit2-0+data2=t 11bit, data3 bit7-2=position, bits 1-0 pinned zero; band derived from the tuning frequency",
  "cases": [
    {
      "case": "en50494-baseline-all-zero-bits",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          0,
          203
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-all-bits-set",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          253,
          255
        ],
        "t": 511
      },
      "if_frequency_mhz": 1400,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 11836000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": "B",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 2040,
        "ub_slot": 7
      }
    },
    {
      "case": "en50494-pin-variant-command-0x5c",
      "expected": {
        "frame_bytes": [
          224,
          16,
          92,
          97,
          50,
          107
        ],
        "t": 306
      },
      "if_frequency_mhz": 1200,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": 107,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1420,
        "ub_slot": 3
      }
    },
    {
      "case": "en50494-pin-zero-is-six-byte",
      "expected": {
        "frame_bytes": [
          224,
          16,
          92,
          0,
          203,
          0
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": 0,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-abs-max-t-1023",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          255,
          255
        ],
        "t": 1023
      },
      "if_frequency_mhz": 3448,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 11836000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": "B",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 2040,
        "ub_slot": 7
      }
    },
    {
      "case": "en50494-field-isolation-ub-bits-7-5",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          160,
          203
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 5
      }
    },
    {
      "case": "en50494-field-isolation-position-bit-4",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          16,
          203
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "B",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-field-isolation-polarization-bit-3",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          8,
          203
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-field-isolation-band-bit-2",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          4,
          203
        ],
        "t": 203
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 11800000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-field-isolation-t-low-byte",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          0,
          204
        ],
        "t": 204
      },
      "if_frequency_mhz": 1002,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50494-field-isolation-t-high-bits",
      "expected": {
        "frame_bytes": [
          224,
          16,
          90,
          1,
          97
        ],
        "t": 353
      },
      "if_frequency_mhz": 1600,
      "protocol": "EN50494",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": "A",
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-baseline-small-values",
      "expected": {
        "frame_bytes": [
          112,
          3,
          132,
          0
        ],
        "t": 900
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-all-bits-set",
      "expected": {
        "frame_bytes": [
          112,
          255,
          58,
          252
        ],
        "t": 1850
      },
      "if_frequency_mhz": 1950,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 11836000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": 63,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 2040,
        "ub_slot": 31
      }
    },
    {
      "case": "en50607-abs-max-t-2047",
      "expected": {
        "frame_bytes": [
          112,
          255,
          255,
          252
        ],
        "t": 2047
      },
      "if_frequency_mhz": 2147,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 11836000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": 63,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 2040,
        "ub_slot": 31
      }
    },
    {
      "case": "en50607-t-zero-boundary",
      "expected": {
        "frame_bytes": [
          112,
          0,
          0,
          0
        ],
        "t": 0
      },
      "if_frequency_mhz": 100,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-pin-variant-command-0x71",
      "expected": {
        "frame_bytes": [
          113,
          141,
          120,
          168,
          255
        ],
        "t": 1400
      },
      "if_frequency_mhz": 1500,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": 255,
        "position": 42,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1420,
        "ub_slot": 17
      }
    },
    {
      "case": "en50607-field-isolation-ub-bits-7-3",
      "expected": {
        "frame_bytes": [
          112,
          11,
          132,
          0
        ],
        "t": 900
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 1
      }
    },
    {
      "case": "en50607-field-isolation-position-bits-7-2",
      "expected": {
        "frame_bytes": [
          112,
          3,
          132,
          4
        ],
        "t": 900
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 1,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-field-isolation-t-low-byte",
      "expected": {
        "frame_bytes": [
          112,
          3,
          232,
          0
        ],
        "t": 1000
      },
      "if_frequency_mhz": 1100,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-polarization-invariant-vertical",
      "expected": {
        "frame_bytes": [
          112,
          3,
          132,
          0
        ],
        "t": 900
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 10700000,
        "polarization": "vertical"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    },
    {
      "case": "en50607-polarization-invariant-horizontal",
      "expected": {
        "frame_bytes": [
          112,
          3,
          132,
          0
        ],
        "t": 900
      },
      "if_frequency_mhz": 1000,
      "protocol": "EN50607",
      "tuning_request": {
        "frequency_khz": 11836000,
        "polarization": "horizontal"
      },
      "ub_assignment": {
        "pin": null,
        "position": 0,
        "tuner_node": "tuner-a",
        "ub_bandwidth_mhz": 46,
        "ub_center_freq_mhz": 1210,
        "ub_slot": 0
      }
    }
  ],
  "spec_source": "SPEC-623 section 6 bit-layout tables (normative; four-implementation source-level consensus tvheadend/VDR/MuMuDVB/minisatip — no clause numbers, issue #145 gap list)",
  "vector_id": "unicable-tuning-message-bit-layout"
}
