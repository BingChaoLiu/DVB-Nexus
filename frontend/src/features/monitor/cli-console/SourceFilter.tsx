// Source filter control (SPEC-405 §4.4, REQ-UI-405-003 / AC-405-04): the
// four-value closed set plus the unfiltered view, as a single-select
// button group (aria-pressed marks the active value). Values render as the
// snake_case wire literals verbatim — the vocabulary IS the contract.
import { CLI_SOURCE_ALL, CLI_SOURCE_VALUES, type SourceSelection } from "./sources";

export function SourceFilter({
  selected,
  onSelectChange,
}: {
  selected: SourceSelection;
  onSelectChange: (selected: SourceSelection) => void;
}) {
  return (
    <div className="dvb-cli-source-filter" role="group" aria-label="source 过滤">
      <button
        type="button"
        aria-pressed={selected === CLI_SOURCE_ALL}
        onClick={() => onSelectChange(CLI_SOURCE_ALL)}
      >
        全部
      </button>
      {CLI_SOURCE_VALUES.map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={selected === value}
          onClick={() => onSelectChange(value)}
        >
          {value}
        </button>
      ))}
    </div>
  );
}
