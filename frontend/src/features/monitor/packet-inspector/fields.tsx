// SPEC-404 §Phase2 — shared presentational rows for the layered structure
// views (#132 OWN face). Values render the wire verbatim: hex/dec/bits are
// presentation conventions, the values themselves undergo zero
// transformation (SPEC-404 §4.4 wire-原样 discipline).

const hex2 = (n: number) => `0x${n.toString(16).padStart(2, "0")}`;
const hex4 = (n: number) => `0x${n.toString(16).padStart(4, "0")}`;

export { hex2, hex4 };

export function FieldRow({
  name,
  testid,
  value,
  note,
}: {
  name: string;
  testid?: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="dvb-pi-field" data-testid={testid}>
      <span className="dvb-pi-field-name">{name}</span>
      <span className="dvb-pi-field-value">{value}</span>
      {note !== undefined && <span className="dvb-pi-field-note">{note}</span>}
    </div>
  );
}
