//+------------------------------------------------------------------+
//|                 Octa_Hybrid_Demo_EA.mq5                          |
//|                 Automated MT5 Trading Expert Advisor             |
//|                 FastAPI ML & Quant Confluence v2.3               |
//+------------------------------------------------------------------+
#property copyright "Exness Institutional Algorithmic Suite"
#property version   "2.30"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/AccountInfo.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>

//====================================================================
// INPUT SETTINGS
//====================================================================

input group "--- General & API Settings ---"
input bool   InpDemoOnlyGuard          = true;                            // Block trading if account is not DEMO
input bool   InpDryRun                 = true;                            // Call the server and log signals, never place orders
input bool   InpAllowTrading           = false;                           // Enable live execution
input string InpDiscordWebhook         = "";                              // Discord Webhook URL (optional)
input string InpApiUrl                 = "http://127.0.0.1:8000/predict"; // Local FastAPI Quant/ML Server
input double InpMinConfidence          = 0.65;                            // Minimum ML model confidence (0.0 to 1.0)
input bool   InpUseSuggestedThreshold = true;                            // Use model suggested threshold if available
input int    InpTimerSeconds           = 5;                               // Timer loop frequency (seconds)
input ulong  InpMagic                  = 1001001;                         // EA Magic Number

input group "--- Risk & Capital Protection ---"
input double InpRiskPerTrade           = 0.25;                            // Risk % per trade (Quarter-Kelly)
input double InpDailyMaxLoss           = 2.0;                             // Daily Max Drawdown % (equity lock)
input int    InpMaxOpenTrades          = 1;                               // Maximum concurrent open positions (1 for $25-$30 account)
input double InpMaxSpreadATRFrac       = 0.15;                            // Max allowed spread as fraction of ATR (cost filter)
input int    InpMaxSpreadPoints        = 0;                               // Maximum allowed spread in points (0 = disabled)

input group "--- Market & Indicators ---"
input string          InpSymbols          = "EURUSDm,GBPUSDm,BTCUSDm,USDJPYm"; // Curated historical winners
input ENUM_TIMEFRAMES InpTimeframe        = PERIOD_M5;                       // Primary Execution Timeframe (M5)
input ENUM_TIMEFRAMES InpHigherTimeframe  = PERIOD_H1;                       // Macro Trend Timeframe (H1)
input int             InpATRPeriod        = 14;                              // ATR Period (Volatility)
input int             InpEntryWindowSecs  = 90;                              // Max entry window seconds after bar open

input group "--- Stop Loss & Take Profit ---"
input double InpATRMultiplierSL        = 1.5;                             // ATR Multiplier for Stop Loss (matches bot 1.5x)
input double InpTPMultiplier           = 2.0;                             // TP Multiplier relative to SL (Risk:Reward = 2.0)
input int    InpMaxHoldBars            = 36;                              // Max holding period in M5 bars (3 hours time exit)
input bool   InpEnableTrailing         = true;                            // Enable dynamic ATR trailing stop

input group "--- Smart Partial Profit & Break-Even ---"
input bool   InpUsePartialTP           = true;                            // Enable 50% partial close at TP1
input double InpPartialTPRatio         = 1.0;                             // TP1 distance as fraction of SL (1.0 = 1:1 RR)
input double InpBreakEvenBufferPips    = 1.0;                             // Pips to lock above/below entry price on BE

//====================================================================
// STRUCTS & GLOBAL STATE
//====================================================================

struct SymbolHandles
{
   string sym;
   int    atr;
};

struct PartialCloseTracker
{
   ulong ticket;
   bool  partial_closed;
   bool  be_locked;
};

CTrade trade;
CAccountInfo account;
CPositionInfo position;
CSymbolInfo symInfo;

string symbols[];
int num_symbols = 0;
SymbolHandles g_handles[];
PartialCloseTracker g_partial_trackers[];

double initial_daily_equity = 0;
int current_day = -1;
bool daily_lock = false;
bool drawdown_alert_sent = false;
int api_consecutive_failures = 0;
datetime api_circuit_breaker_until = 0;

//====================================================================
// HELPER: TIMEFRAME TO STRING
//====================================================================

string GetTimeframeString(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      default:         return "M5";
   }
}

//====================================================================
// INITIALIZATION
//====================================================================

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetMarginMode();
   trade.SetDeviationInPoints(20);

   ushort separator = StringGetCharacter(",", 0);
   num_symbols = StringSplit(InpSymbols, separator, symbols);

   if(num_symbols <= 0)
   {
      Print("Init Error: No valid symbols specified.");
      return INIT_FAILED;
   }

   ArrayResize(g_handles, num_symbols);

   // Pre-allocate persistent indicator handles once to eliminate memory leaks and tick lag
   for(int i = 0; i < num_symbols; i++)
   {
      StringTrimLeft(symbols[i]);
      StringTrimRight(symbols[i]);
      if(symbols[i] == "") continue;

      if(!SymbolSelect(symbols[i], true))
      {
         Print("Warning: Could not select symbol in MarketWatch: ", symbols[i]);
      }

      g_handles[i].sym = symbols[i];
      g_handles[i].atr = iATR(symbols[i], InpTimeframe, InpATRPeriod);

      if(g_handles[i].atr == INVALID_HANDLE)
      {
         Print("Failed to create ATR handle for symbol: ", symbols[i]);
         return INIT_FAILED;
      }
   }

   ResetDailyBaseline();
   EventSetTimer(MathMax(1, InpTimerSeconds));

   PrintFormat("Octa Hybrid EA v2.3 initialized. Symbols: %d | Timeframe: %s (H1: %s) | Server: %s | DryRun: %s",
               num_symbols, GetTimeframeString(InpTimeframe), GetTimeframeString(InpHigherTimeframe),
               InpApiUrl, (InpDryRun ? "true" : "false"));

   if(InpAllowTrading && !InpDryRun)
      SendDiscordMessage("🚀 Octa Hybrid EA v2.3 initialized. Connected to FastAPI server (Live Trading).");
   else if(InpDryRun)
      Print("ℹ️ Running in DRY RUN mode (signals logged, no orders placed).");

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();

   // Clean up indicator handles
   for(int i = 0; i < ArraySize(g_handles); i++)
   {
      if(g_handles[i].atr != INVALID_HANDLE) IndicatorRelease(g_handles[i].atr);
   }

   Print("Octa Hybrid EA stopped cleanly. Handles released.");
}

//====================================================================
// EVENT HANDLERS
//====================================================================

void OnTick()
{
   ManageDailyLimit();
   if(InpUsePartialTP) ManagePartialTPAndBreakEven();
   if(InpEnableTrailing) ManageTrailingStops();
   ManageTimeExits();
}

void OnTimer()
{
   ManageDailyLimit();
   if(InpUsePartialTP) ManagePartialTPAndBreakEven();
   if(InpEnableTrailing) ManageTrailingStops();
   ManageTimeExits();

   if(!InpDryRun)
   {
      if(!InpAllowTrading || daily_lock) return;
      if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) return;
   }
   else
   {
      if(daily_lock) return;
   }

   for(int i = 0; i < num_symbols; i++)
   {
      string sym = symbols[i];
      if(sym == "" || !SymbolSelect(sym, true)) continue;
      if(CountOurPositions() >= InpMaxOpenTrades) break;
      if(HasOpenPosition(sym)) continue;
      
      // Check if this bar is new without consuming it yet
      if(!IsNewBar(sym, false)) continue;

      // Allow entries only during the initial window after bar open
      datetime bar_open_time = iTime(sym, InpTimeframe, 0);
      if(bar_open_time == 0) continue;
      if(TimeCurrent() - bar_open_time > InpEntryWindowSecs)
      {
         PrintFormat("[%s] Skipped: Past entry window (%d seconds since bar open, max allowed: %ds). Skipping bar.",
                     sym, (int)(TimeCurrent() - bar_open_time), InpEntryWindowSecs);
         IsNewBar(sym, true); // Consume so we wait for the next bar
         continue;
      }

      // Retrieve ATR(bar 1) for the cost-based spread filter
      double atr_filter[1];
      if(CopyBuffer(g_handles[i].atr, 0, 1, 1, atr_filter) != 1 || atr_filter[0] <= 0)
      {
         PrintFormat("[%s] Skipped: ATR buffer copy failed. Retrying next tick.", sym);
         continue;
      }
      double atr_bar1 = atr_filter[0];

      // Refresh rates for current ask/bid
      if(!symInfo.Name(sym) || !symInfo.RefreshRates()) continue;
      double ask = symInfo.Ask();
      double bid = symInfo.Bid();
      double spread_price = ask - bid;

      // Cost-based spread filter: (ask - bid) > InpMaxSpreadATRFrac * ATR(bar 1)
      if(InpMaxSpreadATRFrac > 0.0 && spread_price > (InpMaxSpreadATRFrac * atr_bar1))
      {
         PrintFormat("[%s] Skipped: Spread price (%.5f) > %.1f%% of ATR(1) (%.5f > %.5f). Retrying on next timer tick.",
                     sym, spread_price, InpMaxSpreadATRFrac * 100.0, spread_price, InpMaxSpreadATRFrac * atr_bar1);
         continue;
      }

      // Legacy points check if enabled (> 0)
      long current_spread = SymbolInfoInteger(sym, SYMBOL_SPREAD);
      if(InpMaxSpreadPoints > 0 && current_spread > InpMaxSpreadPoints)
      {
         PrintFormat("[%s] Skipped: Current spread (%d) exceeds max allowed (%d). Retrying on next timer tick.",
                     sym, current_spread, InpMaxSpreadPoints);
         continue;
      }

      bool api_success = false;
      double confidence = 0.0;
      double threshold_used = 0.0;
      string model_used = "";

      int signal = EvaluateSignal(i, api_success, confidence, threshold_used, model_used);
      if(!api_success)
      {
         // API call failed; do not consume bar so timer retries next tick
         continue;
      }

      // Spread check and API call succeeded -> consume the bar
      IsNewBar(sym, true);

      if(signal != 0) ExecuteTrade(i, signal, confidence, threshold_used, model_used);
   }
}

//====================================================================
// NEW BAR DETECTION
//====================================================================

bool IsNewBar(string sym, bool update_last_bar = true)
{
   static string tracked_symbols[];
   static datetime last_bars[];
   int count = ArraySize(tracked_symbols);
   int index = -1;

   for(int i = 0; i < count; i++)
   {
      if(tracked_symbols[i] == sym) { index = i; break; }
   }

   if(index == -1)
   {
      ArrayResize(tracked_symbols, count + 1);
      ArrayResize(last_bars, count + 1);
      index = count;
      tracked_symbols[index] = sym;
      last_bars[index] = 0;
   }

   datetime current_bar = iTime(sym, InpTimeframe, 0);
   if(current_bar == 0) return false;
   if(current_bar != last_bars[index])
   {
      if(update_last_bar)
         last_bars[index] = current_bar;
      return true;
   }
   return false;
}

//====================================================================
// DAILY EQUITY BASELINE & LOSS PROTECTION
//====================================================================

void ResetDailyBaseline()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(dt.day_of_year != current_day)
   {
      current_day = dt.day_of_year;
      initial_daily_equity = account.Equity();
      daily_lock = false;
      drawdown_alert_sent = false;
   }
}

void ManageDailyLimit()
{
   ResetDailyBaseline();
   if(initial_daily_equity <= 0) return;

   double loss_percentage = ((initial_daily_equity - account.Equity()) / initial_daily_equity) * 100.0;
   if(loss_percentage >= InpDailyMaxLoss && !daily_lock)
   {
      daily_lock = true;
      CloseOurPositions();
      SendDiscordMessage("⚠️ Daily loss limit reached! Trading halted until tomorrow.");
      drawdown_alert_sent = true;
      PrintFormat("Daily drawdown safety triggered: %.2f%% loss. EA locked.", loss_percentage);
   }
}

//====================================================================
// POSITION MANAGEMENT
//====================================================================

int CountOurPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(position.SelectByIndex(i) && position.Magic() == (long)InpMagic) count++;
   }
   return count;
}

bool HasOpenPosition(string sym)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(position.SelectByIndex(i) && position.Symbol() == sym && position.Magic() == (long)InpMagic) return true;
   }
   return false;
}

void CloseOurPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(position.SelectByIndex(i) && position.Magic() == (long)InpMagic)
      {
         trade.PositionClose(position.Ticket());
      }
   }
}

//====================================================================
// JSON PARSING UTILITY
//====================================================================

double ExtractJsonNumber(const string &json, const string &key)
{
   string needle = "\"" + key + "\":";
   int pos = StringFind(json, needle);
   if(pos < 0) return 0.0;

   int start = pos + StringLen(needle);
   while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' || StringGetCharacter(json, start) == '\t'))
      start++;

   int end = start;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-')
         end++;
      else
         break;
   }

   if(end <= start) return 0.0;
   return StringToDouble(StringSubstr(json, start, end - start));
}

string ExtractJsonString(const string &json, const string &key)
{
   string needle = "\"" + key + "\":";
   int pos = StringFind(json, needle);
   if(pos < 0) return "";

   int start = pos + StringLen(needle);
   while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' || StringGetCharacter(json, start) == '\t'))
      start++;

   if(start < StringLen(json) && StringGetCharacter(json, start) == '\"')
   {
      start++;
      int end = StringFind(json, "\"", start);
      if(end > start)
         return StringSubstr(json, start, end - start);
   }
   return "";
}

//====================================================================
// FASTAPI ML & QUANT INTEGRATION
//====================================================================

int GetAIPrediction(string sym, bool &api_success, double &out_confidence, double &out_threshold, string &out_model_used)
{
   api_success = false;
   out_confidence = 0.0;
   out_threshold = 0.0;
   out_model_used = "";
   if(InpApiUrl == "") return 0;

   // Circuit breaker: skip API calls if triggered after 3 consecutive failures
   if(TimeCurrent() < api_circuit_breaker_until)
   {
      PrintFormat("[%s] API circuit breaker active: skipping API call (%d seconds left).",
                  sym, (int)(api_circuit_breaker_until - TimeCurrent()));
      return 0;
   }

   // 1. Fetch last 300 CLOSED M5 bars (bar 1 to 300), oldest first
   MqlRates m5_rates[];
   ArraySetAsSeries(m5_rates, false);
   int m5_copied = CopyRates(sym, InpTimeframe, 1, 300, m5_rates);
   if(m5_copied < 50)
   {
      PrintFormat("[%s] CopyRates returned insufficient bars: %d / 300. Error: %d",
                  sym, m5_copied, GetLastError());
      return 0;
   }

   // 2. Fetch last 100 CLOSED H1 bars for macro trend alignment
   MqlRates h1_rates[];
   ArraySetAsSeries(h1_rates, false);
   int h1_copied = CopyRates(sym, InpHigherTimeframe, 1, 100, h1_rates);

   string tf_str = GetTimeframeString(InpTimeframe);

   // 3. Construct JSON payload: {"symbol":"...","timeframe":"...","bars":[[t,o,h,l,c,v],...],"h1_bars":[[t,o,h,l,c,v],...]}
   string json = StringFormat("{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"bars\":[", sym, tf_str);

   for(int k = 0; k < m5_copied; k++)
   {
      string bar_str = StringFormat("[%I64d,%.5f,%.5f,%.5f,%.5f,%I64d]",
                                    (long)m5_rates[k].time,
                                    m5_rates[k].open,
                                    m5_rates[k].high,
                                    m5_rates[k].low,
                                    m5_rates[k].close,
                                    (long)m5_rates[k].tick_volume);
      if(k > 0) json += ",";
      json += bar_str;
   }
   json += "]";

   if(h1_copied >= 20)
   {
      json += ",\"h1_bars\":[";
      for(int k = 0; k < h1_copied; k++)
      {
         string bar_str = StringFormat("[%I64d,%.5f,%.5f,%.5f,%.5f,%I64d]",
                                       (long)h1_rates[k].time,
                                       h1_rates[k].open,
                                       h1_rates[k].high,
                                       h1_rates[k].low,
                                       h1_rates[k].close,
                                       (long)h1_rates[k].tick_volume);
         if(k > 0) json += ",";
         json += bar_str;
      }
      json += "]";
   }

   json += "}";

   char data[];
   char result[];
   string result_headers;

   int byte_len = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(byte_len <= 1) return 0;

   ArrayResize(data, byte_len - 1);
   string headers = "Content-Type: application/json\r\n";

   ResetLastError();
   int status = WebRequest("POST", InpApiUrl, headers, 3000, data, result, result_headers);

   if(status != 200)
   {
      api_consecutive_failures++;
      int err = GetLastError();
      if(err == 4060)
         Print("WebRequest Error 4060: Please add 'http://127.0.0.1:8000' to Tools -> Options -> Expert Advisors -> Allow WebRequest.");
      else
         PrintFormat("[%s] FastAPI WebRequest failed (status: %d, fail #%d, error: %d). (Is Uvicorn running on port 8000?)",
                     sym, status, api_consecutive_failures, err);

      if(api_consecutive_failures >= 3)
      {
         api_circuit_breaker_until = TimeCurrent() + 60;
         api_consecutive_failures = 0;
         PrintFormat("⚠️ API Circuit Breaker tripped: 3 consecutive failures. Skipping API calls for 60 seconds (until %s).",
                     TimeToString(api_circuit_breaker_until, TIME_SECONDS));
      }
      return 0;
   }

   // Reset failure counter on successful WebRequest
   api_consecutive_failures = 0;
   api_success = true;

   string response = CharArrayToString(result);

   if(InpDryRun)
   {
      PrintFormat("[DRY RUN] %s %s server response: %s", sym, tf_str, StringSubstr(response, 0, 250));
   }

   // Extract signal, confidence score, and suggested_threshold from the ML model
   int signal = (int)ExtractJsonNumber(response, "signal");
   double confidence = ExtractJsonNumber(response, "confidence");
   double suggested_th = ExtractJsonNumber(response, "suggested_threshold");

   // Choose effective threshold
   double effective_th = InpMinConfidence;
   if(InpUseSuggestedThreshold && suggested_th > 0.0)
   {
      effective_th = MathMax(InpMinConfidence, suggested_th);
   }

   // Signal 0 is HOLD - do not print rejection
   if(signal == 0)
   {
      return 0;
   }

   // Filter out trades with confidence below threshold (only BUY/SELL reach here)
   if(confidence < effective_th)
   {
      PrintFormat("[%s] Signal %d (%s) rejected: Confidence (%.2f%%) is below threshold (%.2f%%)",
                  sym, signal, (signal > 0 ? "BUY" : "SELL"),
                  confidence * 100.0, effective_th * 100.0);
      return 0;
   }

   PrintFormat("[%s] Quant Validated Signal: %d (%s) with Confidence: %.2f%% (Threshold used: %.2f%%)",
               sym, signal, (signal > 0 ? "BUY" : "SELL"),
               confidence * 100.0, effective_th * 100.0);

   out_confidence = confidence;
   out_threshold = effective_th;
   out_model_used = ExtractJsonString(response, "model_used");

   return signal;
}

int EvaluateSignal(int symbol_idx, bool &api_success, double &out_confidence, double &out_threshold, string &out_model_used)
{
   api_success = false;
   string sym = symbols[symbol_idx];
   return GetAIPrediction(sym, api_success, out_confidence, out_threshold, out_model_used);
}

//====================================================================
// LOT SIZE & RISK CALCULATION
//====================================================================

double CalculateVolume(string sym, double stop_distance)
{
   double risk_money = account.Equity() * InpRiskPerTrade / 100.0;
   double tick_size = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0) tick_value = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);

   double volume_step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double min_volume = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double max_volume = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);

   if(tick_size <= 0 || tick_value <= 0 || volume_step <= 0 || stop_distance <= 0) return 0;

   double loss_per_lot = (stop_distance / tick_size) * tick_value;
   if(loss_per_lot <= 0) return 0;

   double volume = MathFloor((risk_money / loss_per_lot) / volume_step) * volume_step;

   if(volume < min_volume)
   {
      PrintFormat("[%s] Skipped: Calculated lot size (%.3f) is below broker minimum (%.3f)",
                  sym, volume, min_volume);
      return 0;
   }

   return NormalizeDouble(MathMin(volume, max_volume), (volume_step < 0.01) ? 3 : 2);
}

//====================================================================
// TRADE JOURNAL
//====================================================================

void WriteTradeJournal(
   string sym,
   string tf,
   string side,
   double confidence,
   double threshold_used,
   double entry,
   double sl,
   double tp,
   double lots,
   double risk_money,
   double spread,
   double atr,
   ulong order_ticket,
   string model_used
)
{
   string filename = "trade_journal.csv";
   bool exists = FileIsExist(filename, 0);

   int handle = FileOpen(filename, FILE_CSV|FILE_READ|FILE_WRITE|FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Failed to open %s for writing trade journal. Error: %d", filename, GetLastError());
      return;
   }

   if(!exists || FileSize(handle) == 0)
   {
      FileWrite(handle,
                "time",
                "symbol",
                "timeframe",
                "side",
                "confidence",
                "threshold_used",
                "entry",
                "sl",
                "tp",
                "lots",
                "risk_money",
                "spread",
                "atr",
                "order_ticket",
                "model_used");
   }

   FileSeek(handle, 0, SEEK_END);

   string time_str = TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);

   FileWrite(handle,
             time_str,
             sym,
             tf,
             side,
             DoubleToString(confidence, 4),
             DoubleToString(threshold_used, 4),
             DoubleToString(entry, digits),
             DoubleToString(sl, digits),
             DoubleToString(tp, digits),
             DoubleToString(lots, 2),
             DoubleToString(risk_money, 2),
             DoubleToString(spread, digits),
             DoubleToString(atr, digits),
             IntegerToString((long)order_ticket),
             model_used);

   FileClose(handle);
   PrintFormat("[%s] Appended order #%I64u to trade_journal.csv", sym, order_ticket);
}

//====================================================================
// EXECUTE TRADE
//====================================================================

void ExecuteTrade(int symbol_idx, int signal, double confidence, double threshold_used, string model_used)
{
   string sym = g_handles[symbol_idx].sym;
   if(!symInfo.Name(sym) || !symInfo.RefreshRates()) return;

   double atr[1];
   if(CopyBuffer(g_handles[symbol_idx].atr, 0, 1, 1, atr) != 1 || atr[0] <= 0) return;

   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   int stop_level = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);

   double stop_distance = MathMax(atr[0] * InpATRMultiplierSL, (stop_level + 2) * point);
   double lots = CalculateVolume(sym, stop_distance);
   if(lots <= 0) return;

   double entry_price = (signal > 0) ? symInfo.Ask() : symInfo.Bid();
   double sl = NormalizeDouble(entry_price + (signal > 0 ? -stop_distance : stop_distance), digits);
   double tp = NormalizeDouble(entry_price + (signal > 0 ? stop_distance * InpTPMultiplier : -stop_distance * InpTPMultiplier), digits);

   if(InpDryRun)
   {
      PrintFormat("[DRY RUN] %s %s lots=%.2f entry=%.*f SL=%.*f TP=%.*f",
                  sym, (signal > 0 ? "BUY" : "SELL"), lots, digits, entry_price, digits, sl, digits, tp);
      return;
   }

   if(InpDemoOnlyGuard && AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
   {
      static bool demo_guard_warned = false;
      if(!demo_guard_warned)
      {
         Print("❌ SAFETY GUARD: InpDemoOnlyGuard is active and account is NOT DEMO! Never placing an order.");
         demo_guard_warned = true;
      }
      return;
   }

   if(!InpAllowTrading)
   {
      PrintFormat("[%s] Live trading is disabled (InpAllowTrading=false). Skipping order placement.", sym);
      return;
   }

   // Configure symbol filling mode dynamically
   trade.SetTypeFillingBySymbol(sym);

   bool sent = (signal > 0) ? trade.Buy(lots, sym, entry_price, sl, tp, "Quant BUY")
                            : trade.Sell(lots, sym, entry_price, sl, tp, "Quant SELL");

   if(sent && trade.ResultRetcode() == TRADE_RETCODE_DONE)
   {
      ulong order_ticket = trade.ResultOrder();
      double risk_money = account.Equity() * (InpRiskPerTrade / 100.0);
      double spread_price = symInfo.Ask() - symInfo.Bid();

      // Register position in partial tracker
      int t_count = ArraySize(g_partial_trackers);
      ArrayResize(g_partial_trackers, t_count + 1);
      g_partial_trackers[t_count].ticket = order_ticket;
      g_partial_trackers[t_count].partial_closed = false;
      g_partial_trackers[t_count].be_locked = false;

      PrintFormat("[%s] %s executed successfully. Lots: %.2f, Entry: %.*f, SL: %.*f, TP: %.*f, Ticket: #%I64u",
                  sym, (signal > 0 ? "BUY" : "SELL"), lots, digits, entry_price, digits, sl, digits, tp, order_ticket);

      // Append trade journal entry
      WriteTradeJournal(sym, GetTimeframeString(InpTimeframe), (signal > 0 ? "BUY" : "SELL"),
                        confidence, threshold_used, entry_price, sl, tp, lots,
                        risk_money, spread_price, atr[0], order_ticket, model_used);

      SendDiscordMessage(StringFormat("✅ %s %s opened by Quant Engine.\nLots: %.2f | Entry: %.*f | SL: %.*f | TP: %.*f | Ticket: #%I64u",
                                      sym, (signal > 0 ? "BUY" : "SELL"), lots, digits, entry_price, digits, sl, digits, tp, order_ticket));
   }
   else
   {
      PrintFormat("[%s] Order execution failed. Retcode: %d (%s)",
                  sym, trade.ResultRetcode(), trade.ResultRetcodeDescription());
   }
}

//====================================================================
// SMART PARTIAL PROFIT & BREAK-EVEN MANAGEMENT
//====================================================================

void ManagePartialTPAndBreakEven()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;

      ulong ticket = position.Ticket();
      string sym = position.Symbol();
      if(!symInfo.Name(sym) || !symInfo.RefreshRates()) continue;

      // Locate tracker index
      int tracker_idx = -1;
      for(int t = 0; t < ArraySize(g_partial_trackers); t++)
      {
         if(g_partial_trackers[t].ticket == ticket) { tracker_idx = t; break; }
      }

      if(tracker_idx == -1)
      {
         int new_idx = ArraySize(g_partial_trackers);
         ArrayResize(g_partial_trackers, new_idx + 1);
         g_partial_trackers[new_idx].ticket = ticket;
         g_partial_trackers[new_idx].partial_closed = false;
         g_partial_trackers[new_idx].be_locked = false;
         tracker_idx = new_idx;
      }

      // If already break-even locked and partial closed, nothing to do here
      if(g_partial_trackers[tracker_idx].partial_closed && g_partial_trackers[tracker_idx].be_locked)
         continue;

      // Locate ATR handle for symbol
      int handle_idx = -1;
      for(int s = 0; s < num_symbols; s++)
      {
         if(g_handles[s].sym == sym) { handle_idx = s; break; }
      }
      if(handle_idx == -1) continue;

      double atr[1];
      if(CopyBuffer(g_handles[handle_idx].atr, 0, 1, 1, atr) != 1 || atr[0] <= 0) continue;

      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double entry = position.PriceOpen();
      double current_sl = position.StopLoss();
      double current_vol = position.Volume();
      double min_vol = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double vol_step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);

      double target_gain = atr[0] * InpPartialTPRatio;
      double be_buffer = InpBreakEvenBufferPips * 10 * point;

      if(position.PositionType() == POSITION_TYPE_BUY)
      {
         double profit_dist = symInfo.Bid() - entry;

         if(profit_dist >= target_gain)
         {
            // 1. Partial close 50% if volume allows
            if(!g_partial_trackers[tracker_idx].partial_closed && current_vol >= (2.0 * min_vol))
            {
               double close_vol = MathFloor((current_vol / 2.0) / vol_step) * vol_step;
               if(close_vol >= min_vol && trade.PositionClosePartial(ticket, close_vol))
               {
                  g_partial_trackers[tracker_idx].partial_closed = true;
                  PrintFormat("[%s] 🎯 TP1 hit: Partial closed %.2f lots on #%I64u", sym, close_vol, ticket);
                  SendDiscordMessage(StringFormat("🎯 [%s] TP1 Reached! Banked %.2f lots on #%I64u.", sym, close_vol, ticket));
               }
            }

            // 2. Lock Break-Even + Buffer
            double candidate_be = NormalizeDouble(entry + be_buffer, digits);
            if(candidate_be > current_sl + point)
            {
               if(trade.PositionModify(ticket, candidate_be, position.TakeProfit()))
               {
                  g_partial_trackers[tracker_idx].be_locked = true;
                  PrintFormat("[%s] 🛡️ Risk-Free lock: SL moved to Break-Even + buffer (%.*f) for #%I64u", sym, digits, candidate_be, ticket);
               }
            }
         }
      }
      else if(position.PositionType() == POSITION_TYPE_SELL)
      {
         double profit_dist = entry - symInfo.Ask();

         if(profit_dist >= target_gain)
         {
            // 1. Partial close 50%
            if(!g_partial_trackers[tracker_idx].partial_closed && current_vol >= (2.0 * min_vol))
            {
               double close_vol = MathFloor((current_vol / 2.0) / vol_step) * vol_step;
               if(close_vol >= min_vol && trade.PositionClosePartial(ticket, close_vol))
               {
                  g_partial_trackers[tracker_idx].partial_closed = true;
                  PrintFormat("[%s] 🎯 TP1 hit: Partial closed %.2f lots on #%I64u", sym, close_vol, ticket);
                  SendDiscordMessage(StringFormat("🎯 [%s] TP1 Reached! Banked %.2f lots on #%I64u.", sym, close_vol, ticket));
               }
            }

            // 2. Lock Break-Even - Buffer
            double candidate_be = NormalizeDouble(entry - be_buffer, digits);
            if(current_sl == 0 || candidate_be < current_sl - point)
            {
               if(trade.PositionModify(ticket, candidate_be, position.TakeProfit()))
               {
                  g_partial_trackers[tracker_idx].be_locked = true;
                  PrintFormat("[%s] 🛡️ Risk-Free lock: SL moved to Break-Even + buffer (%.*f) for #%I64u", sym, digits, candidate_be, ticket);
               }
            }
         }
      }
   }
}

//====================================================================
// TRAILING STOP MANAGEMENT
//====================================================================

void ManageTrailingStops()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;

      string sym = position.Symbol();
      if(!symInfo.Name(sym) || !symInfo.RefreshRates()) continue;

      // Find cached handle index
      int handle_idx = -1;
      for(int s = 0; s < num_symbols; s++)
      {
         if(g_handles[s].sym == sym) { handle_idx = s; break; }
      }
      if(handle_idx == -1) continue;

      double atr[1];
      if(CopyBuffer(g_handles[handle_idx].atr, 0, 1, 1, atr) != 1 || atr[0] <= 0) continue;

      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      int stops = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);

      double min_distance = (stops + 2) * point;
      double trail_distance = MathMax(atr[0] * InpATRMultiplierSL, min_distance);

      double current_sl = position.StopLoss();
      ulong ticket = position.Ticket();

      if(position.PositionType() == POSITION_TYPE_BUY)
      {
         double candidate = NormalizeDouble(symInfo.Bid() - trail_distance, digits);
         if(candidate > current_sl + point && candidate < symInfo.Bid() - min_distance)
         {
            trade.PositionModify(ticket, candidate, position.TakeProfit());
         }
      }
      else if(position.PositionType() == POSITION_TYPE_SELL)
      {
         double candidate = NormalizeDouble(symInfo.Ask() + trail_distance, digits);
         if((current_sl == 0 || candidate < current_sl - point) && candidate > symInfo.Ask() + min_distance)
         {
            trade.PositionModify(ticket, candidate, position.TakeProfit());
         }
      }
   }
}

//====================================================================
// TIME-BASED EXIT MANAGEMENT
//====================================================================

void ManageTimeExits()
{
   if(InpMaxHoldBars <= 0) return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!position.SelectByIndex(i) || position.Magic() != (long)InpMagic) continue;

      string sym = position.Symbol();
      datetime open_time = position.Time();
      if(open_time <= 0) continue;

      int bars_held = iBarShift(sym, InpTimeframe, open_time, false);
      if(bars_held >= InpMaxHoldBars)
      {
         ulong ticket = position.Ticket();
         if(trade.PositionClose(ticket))
         {
            PrintFormat("[%s] Time exit: Position #%I64u closed after %d bars of %s (max %d bars).",
                        sym, ticket, bars_held, GetTimeframeString(InpTimeframe), InpMaxHoldBars);
            SendDiscordMessage(StringFormat("⏱️ [%s] Position #%I64u closed after %d bars (Time Exit).",
                                            sym, ticket, bars_held));
         }
         else
         {
            PrintFormat("[%s] Failed to close position #%I64u on time exit. Retcode: %d (%s)",
                        sym, ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
         }
      }
   }
}

//====================================================================
// DISCORD WEBHOOK
//====================================================================

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

void SendDiscordMessage(string message)
{
   if(InpDiscordWebhook == "") return;

   string json = "{\"content\":\"" + JsonEscape(message) + "\"}";
   char data[], result[];
   string result_headers;

   int copied = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 1) return;
   ArrayResize(data, copied - 1);

   string headers = "Content-Type: application/json\r\n";
   WebRequest("POST", InpDiscordWebhook, headers, 4000, data, result, result_headers);
}
