const decisionCopy = {
  allow: {
    title: "Access allowed",
    subtitle: "The backend approved this verification.",
    symbol: "✓",
    className: "allow"
  },
  deny: {
    title: "Access denied",
    subtitle: "The backend did not approve this verification.",
    symbol: "×",
    className: "deny"
  },
  ask_again: {
    title: "Verification needed",
    subtitle: "Choose another verification action to continue.",
    symbol: "!",
    className: "ask"
  }
};

export default function DecisionPanel({
  result,
  onRecapture,
  onBlink,
  onCode
}) {
  const config = decisionCopy[result.decision];

  return (
    <section className={`decision-card ${config.className}`}>
      <div className="decision-symbol">{config.symbol}</div>
      <p className="section-kicker">VERIFICATION RESULT</p>
      <h2>{config.title}</h2>
      <p className="decision-subtitle">{config.subtitle}</p>

      {result.reason && (
        <div className="result-detail">
          <strong>Reason</strong>
          <span>{result.reason}</span>
        </div>
      )}

      {result.elapsed_ms !== null && result.elapsed_ms !== undefined && (
        <div className="result-detail">
          <strong>Processing time</strong>
          <span>{result.elapsed_ms} ms</span>
        </div>
      )}

      {result.scores && Object.keys(result.scores).length > 0 && (
        <details className="scores-details">
          <summary>View scores</summary>
          <pre>{JSON.stringify(result.scores, null, 2)}</pre>
        </details>
      )}

      {result.decision === "ask_again" && (
        <div className="retry-actions">
          <button className="retry-button" onClick={onRecapture}>
            <span>↻</span>
            <strong>Recapture</strong>
            <small>Take a fresh set of frames</small>
          </button>
          <button className="retry-button" onClick={onBlink}>
            <span>◉</span>
            <strong>Blink</strong>
            <small>Capture eyes closed, then open</small>
          </button>
          <button className="retry-button" onClick={onCode}>
            <span>⌨</span>
            <strong>Enter a code</strong>
            <small>Send code with the latest frame</small>
          </button>
        </div>
      )}

      {result.decision !== "ask_again" && (
        <button className="secondary-button" onClick={onRecapture}>
          Verify another person
        </button>
      )}
    </section>
  );
}