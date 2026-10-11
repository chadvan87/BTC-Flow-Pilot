"""Whale Confirmation Engine settings. Every threshold and weight is a HYPOTHESIS that needs validation."""
from pydantic import BaseModel, Field

class WalletConfig(BaseModel):
    address: str = Field(pattern="^0x[0-9a-fA-F]{40}$")
    label: str = Field("",max_length=40)
    # Wallets known/suspected to be controlled together share a cluster and count as ONE independent wallet.
    cluster: str = Field("",max_length=40)
    # Operator-assigned quality tier (0..2). Not a win probability.
    quality: float = Field(1.0,ge=0,le=2)

class WhaleConfig(BaseModel):
    wallets: list[WalletConfig] = Field(default_factory=list,max_length=30)
    # When on, Risk Engine preflight blocks manual and AUTO entries unless whales SUPPORT the setup side.
    require_confirmation: bool = False
    poll_seconds: int = Field(60,ge=30,le=600)
    stale_after_s: int = Field(180,ge=60,le=1800)
    half_life_min: float = Field(60,ge=5,le=720)
    position_weight: float = Field(.35,ge=0,le=1)     # existing positions weigh less than recent actions
    reduce_weight: float = Field(1.0,ge=0,le=2)       # how strongly REDUCE/CLOSE removes same-side support
    full_size_equity_frac: float = Field(.5,ge=.05,le=5) # action notional / equity at which an action counts fully
    max_wallet_share: float = Field(.5,ge=.1,le=1)    # one cluster may not exceed this share of a side; 1 disables
    min_independent: int = Field(2,ge=1,le=10)
    min_fresh_wallets: int = Field(2,ge=1,le=30)
    bias_threshold: float = Field(.3,ge=.05,le=1)
    min_total_support: float = Field(.2,ge=0,le=10)
    min_contribution: float = Field(.05,ge=0,le=1)
    merge_window_s: int = Field(300,ge=0,le=3600)     # same-direction fills of one wallet/coin within this gap = one action
    history_factor: bool = True
    discovery_min_wallets: int = Field(3,ge=2,le=10)
    discovery_min_quote_volume: float = Field(50e6,ge=0)
    discovery_max_spread_pct: float = Field(.05,gt=0,le=1)
    discovery_max_abs_funding: float = Field(.0005,gt=0,le=.01)

WINDOWS={"15m":15*60_000,"1h":60*60_000,"4h":240*60_000}
MAX_WINDOW_MS=WINDOWS["4h"]
