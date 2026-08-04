type SurveyLedgerProps = {
  workspaceCount: number;
  quarantineCount: number;
  status: string;
};

export function SurveyLedger({
  workspaceCount,
  quarantineCount,
  status,
}: SurveyLedgerProps) {
  return (
    <svg className="ledger-plat" viewBox="0 0 820 310" role="img" aria-label="Platform operations bearing plot">
      <title>Platform operations bearing plot</title>
      <path className="plat-boundary" d="M27 33 501 18l256 61 34 180-429 31L42 246 27 33Z" />
      <path className="plat-lot" d="m27 33 324 93L501 18M351 126l11 164M351 126l406-47M590 58l-68 218M633 49l158 210M42 246l309-120" />
      <path className="plat-bearing" d="M87 209c103-71 188-90 270-58 96 38 173 23 324-57" />
      <circle className="plat-station" cx="87" cy="209" r="7" />
      <circle className="plat-station" cx="357" cy="151" r="7" />
      <circle className="plat-station plat-station--end" cx="681" cy="94" r="7" />
      <g className="plat-copy">
        <text x="66" y="231">DATABASE</text>
        <text x="330" y="178">AUTHORITY</text>
        <text x="650" y="82">PROVIDERS</text>
        <text className="plat-measure" x="53" y="24">OPS CONTROL PLAT 04</text>
        <text className="plat-measure" x="665" y="286">N 18° 42′ E</text>
      </g>
      <g className="plat-readout">
        <text x="505" y="158">{workspaceCount} WORKSPACES</text>
        <text x="505" y="181">{quarantineCount} QUARANTINED</text>
        <text x="505" y="204">{status.toUpperCase()}</text>
      </g>
    </svg>
  );
}
