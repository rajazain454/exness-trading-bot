//+------------------------------------------------------------------+
//|                 Gold_Institutional_Scalper_EA.mq5                |
//|                 High-Precision MT5 Gold (XAUUSDm) Scalper        |
//|                 Magic Number: 777001                             |
//+------------------------------------------------------------------+
#property copyright "Institutional Gold Scalper"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/AccountInfo.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>

//====================================================================
// INPUT SETTINGS
//====================================================================

input group "--- General & Session Settings ---"
input bool   InpAllowTrading          = false;           // Enable live order execution
input bool   InpDryRun                = true;            // Dry run mode (logs only, no orders)
input string InpDiscordWebhook        = "";              // Discord Webhook URL (optional)
input int    InpSessionStartHourUTC   = 8;               // London Open Session start hour (UTC)
input int    InpSessionEndHourUTC     = 16;              // London/NY Overlap session end hour (UTC)
input ulong  InpMagic                 = 777001;          // Dedicated Gold Scalper Magic Number

input group "--- Risk & Lot Size ---"
input double InpRiskPercent           = 0.50;            // Risk % per trade
input double InpMaxDailyLossPercent   = 2.0;             // Daily Max Drawdown % (equity lock)
input int    InpMaxOpenTrades         = 1;               // Max simultaneous Gold trades

input group "--- Strategy & Indicators (M5) ---"
input int    InpEmaFastPeriod         = 9;               // Fast Trend EMA
input int    InpEmaSlowPeriod         = 21;              // Slow Trend EMA
input int    InpEmaTrendPeriod        = 50;              // Baseline Trend EMA
input int    InpAtrPeriod             = 14;              // ATR Period
input double InpMinWickPercent        = 25.0;            // Min absorption wick % required

input group "--- Stop Loss, Take Profit & Break-Even ---"
input double InpAtrMultiplierSL       = 1.3;             // ATR Multiplier for Stop Loss
input double InpAtrMultiplierTP       = 2.0;             // ATR Multiplier for Take Profit (1:1.5 - 1:2 RR)
input bool   InpUsePartialTP          = true;            // Close 50% lot at TP1 (1.0x ATR)
input double InpPartialTpAtrMult      = 1.0;             // TP1 distance in ATR
input double InpBreakEvenBufferUSD    = 0.20;            // Price distance ($) above entry on BE lock
input bool   InpEnableTrailing        = true;            // Enable dynamic ATR trailing stop
input int    InpMaxHoldBars           = 24;              // Max hold bars (2 hours time exit)

//====================================================================
// GLOBAL VARIABLES & HANDLES
//====================================================================

CTrade trade;
CAccountInfo account;
CPositionInfo position;
CSymbolInfo symInfo;

int handle_ema_fast = INVALID_HANDLE;
int handle_ema_slow = INVALID_HANDLE;
int handle_ema_trend = INVALID_HANDLE;
int handle_atr = INVALID_HANDLE;

datetime last_bar_time = 0;
bool daily_lock = false;
int current_day = -1;
double initial_daily_equity = 0.0;

struct GoldTracker
{
   ulong ticket;
   bool  partial_done;
   bool  be_done;
};

GoldTracker g_trackers[];

//====================================================================
// INITIALIZATION
//====================================================================

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetMarginMode();
   trade.SetDeviationInPoints(30);

   string sym = _Symbol;
   if(!symInfo.Name(sym) || !symInfo.Refresh())
   {
      Print("Failed to initialize symbol: ", sym);
      return INIT_FAILED;
   }

   handle_ema_fast = iMA(sym, PERIOD_M5, InpEmaFastPeriod, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema_slow = iMA(sym, PERIOD_M5, InpEmaSlowPeriod, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema_trend = iMA(sym, PERIOD_M5, InpEmaTrendPeriod, 0, MODE_EMA, PRICE_CLOSE);
   handle_atr = iATR(sym, PERIOD_M5, InpAtrPeriod);

   if(handle_ema_fast == INVALID_HANDLE || handle_ema_slow == INVALID_HANDLE ||
      handle_ema_trend == INVALID_HANDLE || handle_atr == INVALID_HANDLE)
   {
      Print("Error creating indicator handles for Gold.");
      return INIT_FAILED;
   }

   ResetDailyBaseline();
   EventSetTimer(3);

   PrintFormat("Gold Institutional Scalper EA initialized on %s (M5). Magic: %I64u | DryRun: %s",
               sym, InpMagic, (InpDryRun ? "true" : "false"));

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   IndicatorRelease(handle_ema_fast);
   IndicatorRelease(handle_ema_slow);
   IndicatorRelease(handle_ema_trend);
   IndicatorRelease(handle_atr);
   Print("Gold Scalper EA stopped cleanly.");
}

//====================================================================
// EVENT HANDLERS
//====================================================================

void OnTick()
{
   ManageDailyLimit();
   if(InpUsePartialTP) ManagePartialAndBE();
   if(InpEnableTrailing) ManageTrailing();
   ManageTimeExits();
}

void OnTimer()
{
   ManageDailyLimit();
   if(InpUsePartialTP) ManagePartialAndBE();
   if(InpEnableTrailing) ManageTrailing();
   ManageTimeExits();

   if(!InpDryRun && (!InpAllowTrading || daily_lock)) return;

   // Check session hours (UTC)
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   if(dt.hour < InpSessionStartHourUTC || dt.hour >= InpSessionEndHourUTC) return;

   // Check new bar
   datetime cur_bar = iTime(_Symbol, PERIOD_M5, 0);
   if(cur_bar == 0 || cur_bar == last_bar_time) return;

   // Check max open trades
   if(CountOurPositions() >= InpMaxOpenTrades) return;

   // Evaluate entry setup on bar 1 (closed bar)
   EvaluateSetup();
   last_bar_time = cur_bar;
}

//====================================================================
// SETUP EVALUATION
//====================================================================

void EvaluateSetup()
{
   double ema_f[2], ema_s[2], ema_t[2], atr_buf[2];
   MqlRates rates[2];

   if(CopyBuffer(handle_ema_fast, 0, 1, 2, ema_f) != 2) return;
   if(CopyBuffer(handle_ema_slow, 0, 1, 2, ema_s) != 2) return;
   if(CopyBuffer(handle_ema_trend, 0, 1, 2, ema_t) != 2) return;
   if(CopyBuffer(handle_atr, 0, 1, 2, atr_buf) != 2) return;
   if(CopyRates(_Symbol, PERIOD_M5, 1, 2, rates) != 2) return;

   double c = rates[1].close;
   double o = rates[1].open;
   double h = rates[1].high;
   double l = rates[1].low;
   double atr_val = atr_buf[1];
   if(atr_val <= 0) return;

   double c_range = h - l;
   if(c_range <= 0) return;

   double lower_wick = (MathMin(o, c) - l) / c_range;
   double upper_wick = (h - MathMax(o, c)) / c_range;
   double min_wick = InpMinWickPercent / 100.0;

   // BUY Setup
   if(ema_f[1] > ema_s[1] && c > ema_t[1])
   {
      if(l <= ema_f[1] && c >= o && lower_wick >= min_wick)
      {
         ExecuteOrder(1, atr_val);
         return;
      }
   }

   // SELL Setup
   if(ema_f[1] < ema_s[1] && c < ema_t[1])
   {
      if(h >= ema_f[1] && c <= o && upper_wick >= min_wick)
      {
         ExecuteOrder(-1, atr_val);
         return;
      }
   }
}

//====================================================================
// EXECUTION & LOT SIZING
//====================================================================

void ExecuteOrder(int side, double atr_val)
{
   if(!symInfo.RefreshRates()) return;

   string sym = _Symbol;
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double entry = (side > 0) ? symInfo.Ask() : symInfo.Bid();
   double stop_dist = atr_val * InpAtrMultiplierSL;

   double sl = NormalizeDouble(side > 0 ? entry - stop_dist : entry + stop_dist, digits);
   double tp = NormalizeDouble(side > 0 ? entry + (stop_dist * InpAtrMultiplierTP) : entry - (stop_dist * InpAtrMultiplierTP), digits);

   // Risk-based lot size
   double risk_usd = account.Equity() * (InpRiskPercent / 100.0);
   double tick_val = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tick_sz <= 0 || tick_val <= 0) return;

   double loss_per_lot = (stop_dist / tick_sz) * tick_val;
   double min_vol = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vol_step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double lots = MathFloor((risk_usd / loss_per_lot) / vol_step) * vol_step;
   lots = MathMax(min_vol, lots);

   if(InpDryRun)
   {
      PrintFormat("[GOLD SCALPER DRY RUN] %s %s | Lots: %.2f | Entry: %.*f | SL: %.*f | TP: %.*f",
                  sym, (side > 0 ? "BUY" : "SELL"), lots, digits, entry, digits, sl, digits, tp);
      return;
   }

   trade.SetTypeFillingBySymbol(sym);
   bool ok = (side > 0) ? trade.Buy(lots, sym, entry, sl, tp, "Gold Scalp BUY")
                        : trade.Sell(lots, sym, entry, sl, tp, "Gold Scalp SELL");

   if(ok && trade.ResultRetcode() == TRADE_RETCODE_DONE)
   {
      ulong ticket = trade.ResultOrder();
      int sz = ArraySize(g_trackers);
      ArrayResize(g_trackers, sz + 1);
      g_trackers[sz].ticket = ticket;
      g_trackers[sz].partial_done = false;
      g_trackers[sz].be_done = false;

      PrintFormat("⚡ Gold Scalp #%I64u executed! Lots: %.2f | SL: %.*f | TP: %.*f", ticket, lots, digits, sl, digits, tp);
      SendDiscord(StringFormat("⚡ [Gold Scalper] %s #%I64u Opened!\nLots: %.2f | Entry: %.*f | SL: %.*f | TP: %.*f",
                               (side > 0 ? "BUY" : "SELL"), ticket, lots, digits, entry, digits, sl, digits, tp));
   }
}

//====================================================================
// PARTIAL TP & BREAK-EVEN
//====================================================================

void ManagePartialAndBE()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;

      ulong ticket = position.Ticket();
      string sym = position.Symbol();
      if(!symInfo.Name(sym) || !symInfo.RefreshRates()) continue;

      double atr[1];
      if(CopyBuffer(handle_atr, 0, 1, 1, atr) != 1 || atr[0] <= 0) continue;

      int t_idx = -1;
      for(int k = 0; k < ArraySize(g_trackers); k++)
      {
         if(g_trackers[k].ticket == ticket) { t_idx = k; break; }
      }
      if(t_idx == -1)
      {
         int sz = ArraySize(g_trackers);
         ArrayResize(g_trackers, sz + 1);
         g_trackers[sz].ticket = ticket;
         g_trackers[sz].partial_done = false;
         g_trackers[sz].be_done = false;
         t_idx = sz;
      }

      if(g_trackers[t_idx].partial_done && g_trackers[t_idx].be_done) continue;

      double entry = position.PriceOpen();
      double cur_vol = position.Volume();
      double min_vol = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double vol_step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double target_tp1 = atr[0] * InpPartialTpAtrMult;

      if(position.PositionType() == POSITION_TYPE_BUY)
      {
         double dist = symInfo.Bid() - entry;
         if(dist >= target_tp1)
         {
            if(!g_trackers[t_idx].partial_done && cur_vol >= (min_vol * 2))
            {
               double close_vol = MathFloor((cur_vol / 2.0) / vol_step) * vol_step;
               if(trade.PositionClosePartial(ticket, close_vol))
               {
                  g_trackers[t_idx].partial_done = true;
                  PrintFormat("🎯 Gold #%I64u TP1 hit: Banked %.2f lots", ticket, close_vol);
                  SendDiscord(StringFormat("🎯 [Gold Scalper] TP1 Hit #%I64u! Banked %.2f lots.", ticket, close_vol));
               }
            }
            double candidate_be = NormalizeDouble(entry + InpBreakEvenBufferUSD, digits);
            if(candidate_be > position.StopLoss())
            {
               if(trade.PositionModify(ticket, candidate_be, position.TakeProfit()))
               {
                  g_trackers[t_idx].be_done = true;
                  PrintFormat("🛡️ Gold #%I64u SL moved to Break-Even (%.*f)", ticket, digits, candidate_be);
               }
            }
         }
      }
      else if(position.PositionType() == POSITION_TYPE_SELL)
      {
         double dist = entry - symInfo.Ask();
         if(dist >= target_tp1)
         {
            if(!g_trackers[t_idx].partial_done && cur_vol >= (min_vol * 2))
            {
               double close_vol = MathFloor((cur_vol / 2.0) / vol_step) * vol_step;
               if(trade.PositionClosePartial(ticket, close_vol))
               {
                  g_trackers[t_idx].partial_done = true;
                  PrintFormat("🎯 Gold #%I64u TP1 hit: Banked %.2f lots", ticket, close_vol);
                  SendDiscord(StringFormat("🎯 [Gold Scalper] TP1 Hit #%I64u! Banked %.2f lots.", ticket, close_vol));
               }
            }
            double candidate_be = NormalizeDouble(entry - InpBreakEvenBufferUSD, digits);
            if(position.StopLoss() == 0 || candidate_be < position.StopLoss())
            {
               if(trade.PositionModify(ticket, candidate_be, position.TakeProfit()))
               {
                  g_trackers[t_idx].be_done = true;
                  PrintFormat("🛡️ Gold #%I64u SL moved to Break-Even (%.*f)", ticket, digits, candidate_be);
               }
            }
         }
      }
   }
}

//====================================================================
// TRAILING & TIME EXITS
//====================================================================

void ManageTrailing()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;
      string sym = position.Symbol();
      if(!symInfo.Name(sym) || !symInfo.RefreshRates()) continue;

      double atr[1];
      if(CopyBuffer(handle_atr, 0, 1, 1, atr) != 1 || atr[0] <= 0) continue;

      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double trail_dist = atr[0] * InpAtrMultiplierSL;
      ulong ticket = position.Ticket();

      if(position.PositionType() == POSITION_TYPE_BUY)
      {
         double cand = NormalizeDouble(symInfo.Bid() - trail_dist, digits);
         if(cand > position.StopLoss()) trade.PositionModify(ticket, cand, position.TakeProfit());
      }
      else if(position.PositionType() == POSITION_TYPE_SELL)
      {
         double cand = NormalizeDouble(symInfo.Ask() + trail_dist, digits);
         if(position.StopLoss() == 0 || cand < position.StopLoss()) trade.PositionModify(ticket, cand, position.TakeProfit());
      }
   }
}

void ManageTimeExits()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;
      int bars_held = iBarShift(_Symbol, PERIOD_M5, position.Time(), false);
      if(bars_held >= InpMaxHoldBars)
      {
         trade.PositionClose(position.Ticket());
         PrintFormat("⏱️ Gold #%I64u closed after %d bars (Time Exit).", position.Ticket(), bars_held);
      }
   }
}

//====================================================================
// UTILITIES
//====================================================================

int CountOurPositions()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(position.SelectByIndex(i) && position.Magic() == (long)InpMagic) c++;
   }
   return c;
}

void ResetDailyBaseline()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != current_day)
   {
      current_day = dt.day_of_year;
      initial_daily_equity = account.Equity();
      daily_lock = false;
   }
}

void ManageDailyLimit()
{
   ResetDailyBaseline();
   if(initial_daily_equity <= 0) return;
   double loss = ((initial_daily_equity - account.Equity()) / initial_daily_equity) * 100.0;
   if(loss >= InpMaxDailyLossPercent && !daily_lock)
   {
      daily_lock = true;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(position.SelectByIndex(i) && position.Magic() == (long)InpMagic)
            trade.PositionClose(position.Ticket());
      }
      PrintFormat("⚠️ Gold Scalper Daily drawdown lock triggered (%.2f%%). Halted.", loss);
   }
}

void SendDiscord(string msg)
{
   if(InpDiscordWebhook == "") return;
   string json = "{\"content\":\"" + msg + "\"}";
   char data[], res[];
   string hdrs = "Content-Type: application/json\r\n";
   int len = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 1) { ArrayResize(data, len - 1); WebRequest("POST", InpDiscordWebhook, hdrs, 3000, data, res, hdrs); }
}
