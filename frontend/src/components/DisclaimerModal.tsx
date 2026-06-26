interface Props {
  onAccept: () => void
}

export function DisclaimerModal({ onAccept }: Props) {
  return (
    <div className="modal-overlay">
      <div className="modal disclaimer-modal">
        <div className="modal-title">Risk Disclaimer</div>
        <div className="disclaimer-body">
          <p>
            This software connects to your MetaTrader 5 account and automatically places, modifies,
            and closes live orders using real funds. By enabling it, you accept full responsibility
            for every order it submits and every position it opens or closes on your behalf.
          </p>
          <p>
            <strong>
              Trading carries a substantial risk of loss and is not suitable for everyone.
            </strong>{' '}
            Leveraged trading of forex, indices, metals, commodities, and cryptocurrencies can move
            rapidly against you, and you may lose some, all, or — because positions are leveraged —
            more than the capital you deposit. Only trade with money you can afford to lose
            entirely.
          </p>
          <p>
            The signals this bot acts on are generated automatically and are not financial,
            investment, legal, or tax advice. Nothing it does constitutes a recommendation,
            solicitation, or offer to buy or sell any instrument. Past or simulated performance is
            not a reliable indicator of future results. If you are unsure whether automated trading
            is appropriate for you, seek advice from an independent, licensed professional.
          </p>
          <p>
            The software is provided “as is” and “as available”, without warranty of any kind,
            express or implied. Order execution depends on your broker, your platform, your internet
            connection, and prevailing market conditions — slippage, widened spreads, requotes,
            rejected or partially filled orders, latency, and platform or connectivity downtime can
            and do occur, and may cause the bot to behave in ways you did not intend. To the fullest
            extent permitted by law, the developer accepts no liability for any loss, damage, or
            cost arising from your use of this software.
          </p>
          <p>
            You are solely responsible for monitoring your account, managing your own risk, and
            ensuring that automated trading is permitted in your jurisdiction. Run the bot on a demo
            account until you fully understand its behaviour.
          </p>
        </div>
        <div className="modal-actions">
          <button className="btn primary" onClick={onAccept}>
            I understand and accept the risks
          </button>
        </div>
      </div>
    </div>
  )
}
