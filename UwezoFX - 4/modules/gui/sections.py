# modules/gui/sections.py
import tkinter as tk
from tkinter import ttk
from .widgets import ModernCard, MiniChart, ScrollableFrame, ModernUI, AnimatedProgressBar
from modules.utils.helpers import darken_color, lighten_color

def create_dashboard_section(parent, colors, app):
    """Create the dashboard section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    # Summary cards (Balance, Equity, Drawdown, Today Trades)
    summary_frame = tk.Frame(frame, bg=colors['bg_dark'])
    summary_frame.pack(fill=tk.X, padx=20, pady=10)

    cards = [
        ('Balance', 'balance_val', '$0.00', colors['accent_primary']),
        ('Equity', 'equity_val', '$0.00', colors['accent_success']),
        ('Drawdown', 'drawdown_val', '0.00%', colors['accent_warning']),
        ('Today Trades', 'today_trades_val', '0', colors['accent_info']),
    ]

    for i, (label, var, default, color) in enumerate(cards):
        card = ModernCard(summary_frame, width=200)
        card.grid(row=0, column=i, padx=5, sticky='nsew')
        summary_frame.grid_columnconfigure(i, weight=1)

        tk.Label(card.content, text=label, font=('Segoe UI', 11),
                 fg=colors['text_secondary'], bg=colors['bg_card']).pack(pady=(5,0))
        value_label = tk.Label(card.content, text=default,
                               font=('Montserrat', 20, 'bold'),
                               fg=color, bg=colors['bg_card'])
        value_label.pack(pady=(0,10))
        setattr(app, var, value_label)

    # Chart
    chart_frame = ModernCard(frame, title="Price Chart")
    chart_frame.pack(fill=tk.X, padx=20, pady=10)
    app.mini_chart = MiniChart(chart_frame.content, width=800, height=100)
    app.mini_chart.pack(fill=tk.X)

    # Status cards (Signal, Auto Trading, Bot Status)
    status_frame = tk.Frame(frame, bg=colors['bg_dark'])
    status_frame.pack(fill=tk.X, padx=20, pady=10)

    signal_card = ModernCard(status_frame, title="Current Signal")
    signal_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
    app.signal_badge = tk.Label(signal_card.content, text="NEUTRAL",
                                font=('Montserrat', 24, 'bold'),
                                fg=colors['text_secondary'], bg=colors['bg_card'])
    app.signal_badge.pack(pady=10)

    auto_card = ModernCard(status_frame, title="Auto Trading")
    auto_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
    app.auto_var = tk.BooleanVar(value=False)
    auto_check = tk.Checkbutton(auto_card.content, variable=app.auto_var,
                                bg=colors['bg_card'], fg=colors['accent_success'],
                                selectcolor=colors['bg_card'], command=app.toggle_auto_trading)
    auto_check.pack(pady=10)

    auto_settings_frame = tk.Frame(auto_card.content, bg=colors['bg_card'])
    auto_settings_frame.pack(pady=10, fill=tk.X, padx=10)
    tk.Label(auto_settings_frame, text="Bot Lot Size:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=5)
    app.bot_lot_size_entry = tk.Entry(auto_settings_frame, width=10,
                                      bg=colors['bg_sidebar'], fg=colors['text_primary'],
                                      insertbackground=colors['text_primary'], bd=0, font=('Segoe UI', 10))
    app.bot_lot_size_entry.pack(side=tk.LEFT, padx=5)
    app.bot_lot_size_entry.insert(0, str(app.config.fixed_lot_size))
    app.bot_lot_size_entry.bind('<KeyRelease>', app.update_bot_lot_size)

    bot_card = ModernCard(status_frame, title="Bot Status")
    bot_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
    app.bot_status = tk.Label(bot_card.content, text="STOPPED",
                              font=('Montserrat', 16, 'bold'),
                              fg=colors['accent_danger'], bg=colors['bg_card'])
    app.bot_status.pack(pady=10)

    # Reversal section
    reversal_frame = tk.Frame(frame, bg=colors['bg_dark'])
    reversal_frame.pack(fill=tk.X, padx=20, pady=10)

    reversal_card = ModernCard(reversal_frame, title="⚡ SIGNAL REVERSAL TRADING (11 CONFIRMATIONS)")
    reversal_card.pack(fill=tk.X)

    button_frame = tk.Frame(reversal_card.content, bg=colors['bg_card'])
    button_frame.pack(pady=10)

    app.reversal_button = ModernUI.create_animated_button(
        button_frame, "🔴 REVERSAL MODE: OFF", app.toggle_reversal_mode, 'danger', width=25
    )
    app.reversal_button.pack(side=tk.LEFT, padx=5)

    status_indicator_frame = tk.Frame(button_frame, bg=colors['bg_card'])
    status_indicator_frame.pack(side=tk.LEFT, padx=20)

    tk.Label(status_indicator_frame, text="Last Reversal:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', padx=5)
    app.last_reversal_label = tk.Label(status_indicator_frame, text="Never",
                                       fg=colors['text_primary'], bg=colors['bg_card'],
                                       font=('Segoe UI', 10, 'bold'))
    app.last_reversal_label.grid(row=0, column=1, sticky='w', padx=5)

    tk.Label(status_indicator_frame, text="Trades Executed:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w', padx=5)
    app.reversal_trades_label = tk.Label(status_indicator_frame, text="0/5",
                                         fg=colors['accent_info'], bg=colors['bg_card'],
                                         font=('Segoe UI', 10, 'bold'))
    app.reversal_trades_label.grid(row=1, column=1, sticky='w', padx=5)

    confidence_frame = tk.Frame(reversal_card.content, bg=colors['bg_card'])
    confidence_frame.pack(fill=tk.X, pady=5, padx=20)

    tk.Label(confidence_frame, text="Min Confidence:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=5)

    app.min_confidence_var = tk.StringVar(value="70")
    min_conf_spin = tk.Spinbox(confidence_frame, from_=0, to=100, textvariable=app.min_confidence_var,
                               width=5, bg=colors['bg_sidebar'], fg=colors['text_primary'], bd=0,
                               font=('Segoe UI', 10))
    min_conf_spin.pack(side=tk.LEFT, padx=5)
    min_conf_spin.bind('<KeyRelease>', app.update_reversal_confidence)

    tk.Label(confidence_frame, text="%",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).pack(side=tk.LEFT)

    app.confidence_meter = AnimatedProgressBar(confidence_frame, width=200, height=10,
                                               fg_color=colors['accent_success'])
    app.confidence_meter.pack(side=tk.RIGHT, padx=10)

    settings_btn = ModernUI.create_animated_button(button_frame, "⚙️ Settings",
                                                   lambda: app.switch_section('settings'), 'info')
    settings_btn.pack(side=tk.RIGHT, padx=5)

    # Quick manual trade (PIP-based)
    trade_frame = tk.Frame(frame, bg=colors['bg_dark'])
    trade_frame.pack(fill=tk.X, padx=20, pady=10)

    trade_card = ModernCard(trade_frame, title="Quick Manual Trade (PIP-based)")
    trade_card.pack(fill=tk.X)

    input_frame = tk.Frame(trade_card.content, bg=colors['bg_card'])
    input_frame.pack(pady=10)

    tk.Label(input_frame, text="Lot Size:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=0, column=0, padx=5, pady=5)

    app.lot_size = tk.Entry(input_frame, width=10, bg=colors['bg_sidebar'],
                            fg=colors['text_primary'], insertbackground=colors['text_primary'],
                            bd=0, font=('Segoe UI', 10))
    app.lot_size.grid(row=0, column=1, padx=5, pady=5)
    app.lot_size.insert(0, "0.01")
    ModernUI.add_glow_effect(app.lot_size, colors['accent_primary'])

    btn_frame = tk.Frame(trade_card.content, bg=colors['bg_card'])
    btn_frame.pack(pady=10)

    buy_btn = ModernUI.create_animated_button(btn_frame, "BUY", lambda: app.execute_manual_trade('BUY'), 'success')
    buy_btn.pack(side=tk.LEFT, padx=5)
    sell_btn = ModernUI.create_animated_button(btn_frame, "SELL", lambda: app.execute_manual_trade('SELL'), 'danger')
    sell_btn.pack(side=tk.LEFT, padx=5)

    # Notifications
    notif_frame = tk.Frame(frame, bg=colors['bg_dark'])
    notif_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    notif_card = ModernCard(notif_frame, title="Recent Notifications")
    notif_card.pack(fill=tk.BOTH, expand=True)

    app.notifications_list = tk.Listbox(notif_card.content, bg=colors['bg_card'],
                                        fg=colors['text_primary'], selectbackground=colors['hover'],
                                        bd=0, highlightthickness=0, font=('Segoe UI', 10))
    app.notifications_list.pack(fill=tk.BOTH, expand=True)

    return frame


def create_trading_section(parent, colors, app):
    """Create the trading signal section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    header_frame = tk.Frame(frame, bg=colors['bg_dark'])
    header_frame.pack(fill=tk.X, padx=20, pady=10)

    tk.Label(header_frame, text="Current Trading Signal",
             font=('Montserrat', 16, 'bold'),
             fg=colors['text_primary'], bg=colors['bg_dark']).pack(side=tk.LEFT)

    sts_frame = tk.Frame(header_frame, bg=colors['bg_dark'])
    sts_frame.pack(side=tk.RIGHT)

    tk.Label(sts_frame, text="STS Mode:",
             fg=colors['text_secondary'], bg=colors['bg_dark'],
             font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)

    app.sts_var = tk.BooleanVar(value=False)
    sts_check = tk.Checkbutton(sts_frame, variable=app.sts_var,
                               bg=colors['bg_dark'], fg=colors['accent_success'],
                               selectcolor=colors['bg_dark'], command=app.toggle_sts)
    sts_check.pack(side=tk.LEFT)

    signal_card = ModernCard(frame, title="Signal Details")
    signal_card.pack(fill=tk.X, padx=20, pady=10)

    app.trading_signal = tk.Label(signal_card.content, text="NEUTRAL",
                                  font=('Montserrat', 32, 'bold'),
                                  fg=colors['text_secondary'], bg=colors['bg_card'])
    app.trading_signal.pack(pady=20)

    details_frame = tk.Frame(signal_card.content, bg=colors['bg_card'])
    details_frame.pack(pady=10)

    details = [
        ('Entry Price:', 'entry_price_label', '—'),
        ('Entry Type:', 'entry_type_label', '—'),
        ('Trades Remaining:', 'trades_remaining_label', '0/5'),
        ('Aggressive Mode:', 'aggressive_label', 'INACTIVE'),
    ]

    for i, (label, attr, default) in enumerate(details):
        row = i // 2
        col = i % 2
        tk.Label(details_frame, text=label,
                 fg=colors['text_secondary'], bg=colors['bg_card'],
                 font=('Segoe UI', 11)).grid(row=row, column=col*2, sticky='w', padx=10, pady=5)
        value_label = tk.Label(details_frame, text=default,
                               fg=colors['text_primary'], bg=colors['bg_card'],
                               font=('Segoe UI', 11, 'bold'))
        value_label.grid(row=row, column=col*2+1, sticky='w', padx=10, pady=5)
        setattr(app, attr, value_label)

    comment_frame = tk.Frame(signal_card.content, bg=colors['bg_card'])
    comment_frame.pack(fill=tk.X, pady=10)

    tk.Label(comment_frame, text="Signal Comment:",
             fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 11)).pack(anchor='w', padx=20)
    app.signal_comment = tk.Label(comment_frame, text="—",
                                  fg=colors['text_primary'], bg=colors['bg_card'],
                                  wraplength=800, font=('Segoe UI', 11))
    app.signal_comment.pack(anchor='w', padx=20, pady=5)

    return frame


def create_positions_section(parent, colors, app):
    """Create the positions and orders section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    count_frame = tk.Frame(frame, bg=colors['bg_dark'])
    count_frame.pack(fill=tk.X, padx=20, pady=10)

    tk.Label(count_frame, text="Active Trades & Orders",
             font=('Montserrat', 16, 'bold'),
             fg=colors['text_primary'], bg=colors['bg_dark']).pack(side=tk.LEFT)

    badge_frame = tk.Frame(count_frame, bg=colors['bg_dark'])
    badge_frame.pack(side=tk.RIGHT)

    app.active_positions_count = tk.Label(badge_frame, text="Active Trades: 0",
                                          font=('Segoe UI', 12, 'bold'),
                                          fg=colors['accent_success'], bg=colors['bg_dark'])
    app.active_positions_count.pack(side=tk.LEFT, padx=10)

    app.pending_orders_count = tk.Label(badge_frame, text="Pending Orders: 0",
                                        font=('Segoe UI', 12, 'bold'),
                                        fg=colors['accent_info'], bg=colors['bg_dark'])
    app.pending_orders_count.pack(side=tk.LEFT, padx=10)

    bulk_card = ModernCard(frame, title="Bulk Actions")
    bulk_card.pack(fill=tk.X, padx=20, pady=10)

    btn_frame = tk.Frame(bulk_card.content, bg=colors['bg_card'])
    btn_frame.pack(pady=10)

    actions = [
        ('Close Losing', app.close_losing_positions, 'warning'),
        ('Close Profitable', app.close_profitable_positions, 'success'),
        ('Close All', app.close_all_positions, 'danger'),
        ('Cancel All Orders', app.cancel_all_orders, 'info'),
    ]

    for text, cmd, style in actions:
        btn = ModernUI.create_animated_button(btn_frame, text, cmd, style)
        btn.pack(side=tk.LEFT, padx=5)

    notebook = ttk.Notebook(frame)
    notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    # Positions tab
    positions_frame = tk.Frame(notebook, bg=colors['bg_dark'])
    notebook.add(positions_frame, text="Open Positions")

    columns = ('Ticket', 'Symbol', 'Type', 'Volume', 'Entry', 'Current', 'P&L', 'SL', 'TP', 'Locked')
    app.positions_tree = ttk.Treeview(positions_frame, columns=columns, show='headings', height=15)

    for col in columns:
        app.positions_tree.heading(col, text=col)
        app.positions_tree.column(col, width=90)

    app.positions_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar = ttk.Scrollbar(positions_frame, orient="vertical", command=app.positions_tree.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.positions_tree.configure(yscrollcommand=scrollbar.set)
    app.positions_tree.bind('<Double-1>', app.on_position_double_click)

    # Orders tab
    orders_frame = tk.Frame(notebook, bg=colors['bg_dark'])
    notebook.add(orders_frame, text="Pending Orders")

    order_columns = ('Ticket', 'Symbol', 'Type', 'Volume', 'Price', 'SL', 'TP', 'Expiration')
    app.orders_tree = ttk.Treeview(orders_frame, columns=order_columns, show='headings', height=15)

    for col in order_columns:
        app.orders_tree.heading(col, text=col)
        app.orders_tree.column(col, width=100)

    app.orders_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    order_scrollbar = ttk.Scrollbar(orders_frame, orient="vertical", command=app.orders_tree.yview)
    order_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.orders_tree.configure(yscrollcommand=order_scrollbar.set)

    # History tab
    history_frame = tk.Frame(notebook, bg=colors['bg_dark'])
    notebook.add(history_frame, text="Trade History")

    history_columns = ('Ticket', 'Symbol', 'Type', 'Volume', 'Entry Price', 'Profit', 'Entry Time')
    app.history_tree = ttk.Treeview(history_frame, columns=history_columns, show='headings', height=15)

    for col in history_columns:
        app.history_tree.heading(col, text=col)
        app.history_tree.column(col, width=100)

    app.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    history_scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=app.history_tree.yview)
    history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.history_tree.configure(yscrollcommand=history_scrollbar.set)

    return frame


def create_news_section(parent, colors, app):
    """Create the news and sentiment section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    header_frame = tk.Frame(frame, bg=colors['bg_dark'])
    header_frame.pack(fill=tk.X, padx=20, pady=10)

    tk.Label(header_frame, text="Myfxbook News & Sentiment",
             font=('Montserrat', 16, 'bold'),
             fg=colors['text_primary'], bg=colors['bg_dark']).pack(side=tk.LEFT)

    refresh_btn = ModernUI.create_animated_button(header_frame, "Refresh", app.fetch_news, 'primary')
    refresh_btn.pack(side=tk.RIGHT)

    sentiment_frame = tk.Frame(frame, bg=colors['bg_dark'])
    sentiment_frame.pack(fill=tk.X, padx=20, pady=5)

    tk.Label(sentiment_frame, text="Use News Sentiment:",
             fg=colors['text_secondary'], bg=colors['bg_dark'],
             font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)

    app.news_sentiment_var = tk.BooleanVar(value=False)
    sentiment_check = tk.Checkbutton(sentiment_frame, variable=app.news_sentiment_var,
                                     bg=colors['bg_dark'], fg=colors['accent_success'],
                                     selectcolor=colors['bg_dark'], command=app.toggle_news_sentiment)
    sentiment_check.pack(side=tk.LEFT)

    market_card = ModernCard(frame, title="Market Sentiment")
    market_card.pack(fill=tk.X, padx=20, pady=10)

    meter_frame = tk.Frame(market_card.content, bg=colors['bg_card'])
    meter_frame.pack(pady=10)

    app.sentiment_label = tk.Label(meter_frame, text="NEUTRAL",
                                   font=('Montserrat', 18, 'bold'),
                                   fg=colors['text_secondary'], bg=colors['bg_card'])
    app.sentiment_label.pack()

    app.sentiment_score = tk.Label(meter_frame, text="Score: 0.00",
                                   font=('Segoe UI', 12),
                                   fg=colors['text_secondary'], bg=colors['bg_card'])
    app.sentiment_score.pack()

    app.sentiment_confidence = tk.Label(meter_frame, text="Confidence: LOW",
                                        font=('Segoe UI', 11),
                                        fg=colors['text_secondary'], bg=colors['bg_card'])
    app.sentiment_confidence.pack()

    summary_frame = tk.Frame(market_card.content, bg=colors['bg_card'])
    summary_frame.pack(pady=10)

    app.high_impact_label = tk.Label(summary_frame, text="High Impact: 0",
                                     font=('Segoe UI', 11, 'bold'),
                                     fg=colors['accent_danger'], bg=colors['bg_card'])
    app.high_impact_label.pack(side=tk.LEFT, padx=10)

    app.medium_impact_label = tk.Label(summary_frame, text="Medium Impact: 0",
                                       font=('Segoe UI', 11, 'bold'),
                                       fg=colors['accent_warning'], bg=colors['bg_card'])
    app.medium_impact_label.pack(side=tk.LEFT, padx=10)

    app.bullish_label = tk.Label(summary_frame, text="Bullish: 0",
                                 font=('Segoe UI', 11, 'bold'),
                                 fg=colors['accent_success'], bg=colors['bg_card'])
    app.bullish_label.pack(side=tk.LEFT, padx=10)

    app.bearish_label = tk.Label(summary_frame, text="Bearish: 0",
                                 font=('Segoe UI', 11, 'bold'),
                                 fg=colors['accent_danger'], bg=colors['bg_card'])
    app.bearish_label.pack(side=tk.LEFT, padx=10)

    rec_card = ModernCard(frame, title="Trading Recommendations")
    rec_card.pack(fill=tk.X, padx=20, pady=10)

    app.recommendations_text = tk.Text(rec_card.content, height=5,
                                       bg=colors['bg_card'], fg=colors['text_primary'],
                                       wrap=tk.WORD, font=('Segoe UI', 11), bd=0)
    app.recommendations_text.pack(fill=tk.X, padx=10, pady=10)

    news_card = ModernCard(frame, title="Economic Calendar")
    news_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    app.news_canvas = tk.Canvas(news_card.content, bg=colors['bg_dark'], highlightthickness=0)
    news_scrollbar = tk.Scrollbar(news_card.content, orient=tk.VERTICAL, command=app.news_canvas.yview)
    app.news_items_frame = tk.Frame(app.news_canvas, bg=colors['bg_dark'])

    app.news_canvas.configure(yscrollcommand=news_scrollbar.set)
    app.news_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    news_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.news_canvas.create_window((0, 0), window=app.news_items_frame, anchor='nw', width=app.news_canvas.winfo_width())
    app.news_items_frame.bind('<Configure>', app.on_news_frame_configure)

    return frame


def create_settings_section(parent, colors, app):
    """Create the settings section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    # Broker Connection Card
    broker_card = ModernCard(frame, title="🔌 Broker Connection (MetaTrader 5)")
    broker_card.pack(fill=tk.X, padx=20, pady=10)

    status_frame = tk.Frame(broker_card.content, bg=colors['bg_card'])
    status_frame.pack(fill=tk.X, padx=10, pady=10)

    app.broker_status_label = tk.Label(status_frame, text="● DISCONNECTED",
                                       font=('Segoe UI', 12, 'bold'),
                                       fg=colors['accent_danger'], bg=colors['bg_card'])
    app.broker_status_label.pack(side=tk.LEFT, padx=10)

    app.broker_account_label = tk.Label(status_frame, text="No account connected",
                                        font=('Segoe UI', 10),
                                        fg=colors['text_secondary'], bg=colors['bg_card'])
    app.broker_account_label.pack(side=tk.LEFT, padx=20)

    notebook = ttk.Notebook(broker_card.content)
    notebook.pack(fill=tk.X, padx=10, pady=10)

    # Local MT5 Tab
    local_frame = tk.Frame(notebook, bg=colors['bg_card'])
    notebook.add(local_frame, text="Local MT5 Terminal")

    info_label = tk.Label(local_frame, text="Connect to locally installed MetaTrader 5 terminal",
                          fg=colors['text_secondary'], bg=colors['bg_card'], font=('Segoe UI', 10))
    info_label.pack(anchor='w', padx=10, pady=5)

    local_btn_frame = tk.Frame(local_frame, bg=colors['bg_card'])
    local_btn_frame.pack(pady=10)

    app.connect_local_btn = ModernUI.create_animated_button(local_btn_frame, "🔌 Connect to Local MT5",
                                                            app.connect_local_mt5, 'primary')
    app.connect_local_btn.pack(side=tk.LEFT, padx=5)

    app.disconnect_btn = ModernUI.create_animated_button(local_btn_frame, "❌ Disconnect",
                                                         app.disconnect_mt5, 'danger')
    app.disconnect_btn.pack(side=tk.LEFT, padx=5)
    app.disconnect_btn.config(state='disabled')

    # Remote Login Tab
    remote_frame = tk.Frame(notebook, bg=colors['bg_card'])
    notebook.add(remote_frame, text="Direct Broker Login")

    info_label2 = tk.Label(remote_frame, text="Connect directly to your broker (requires server details)",
                           fg=colors['text_secondary'], bg=colors['bg_card'], font=('Segoe UI', 10))
    info_label2.pack(anchor='w', padx=10, pady=5)

    login_form = tk.Frame(remote_frame, bg=colors['bg_card'])
    login_form.pack(padx=10, pady=10)

    tk.Label(login_form, text="Server:", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.broker_server = tk.Entry(login_form, width=30, bg=colors['bg_sidebar'],
                                 fg=colors['text_primary'], insertbackground=colors['text_primary'],
                                 bd=0, font=('Segoe UI', 10))
    app.broker_server.grid(row=0, column=1, padx=5, pady=5)
    app.broker_server.insert(0, "ICMarkets-Demo")

    tk.Label(login_form, text="Login:", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.broker_login = tk.Entry(login_form, width=30, bg=colors['bg_sidebar'],
                                fg=colors['text_primary'], insertbackground=colors['text_primary'],
                                bd=0, font=('Segoe UI', 10))
    app.broker_login.grid(row=1, column=1, padx=5, pady=5)

    tk.Label(login_form, text="Password:", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 10)).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.broker_password = tk.Entry(login_form, width=30, show="*", bg=colors['bg_sidebar'],
                                   fg=colors['text_primary'], insertbackground=colors['text_primary'],
                                   bd=0, font=('Segoe UI', 10))
    app.broker_password.grid(row=2, column=1, padx=5, pady=5)

    app.save_credentials_var = tk.BooleanVar(value=False)
    save_cb = tk.Checkbutton(login_form, text="Save credentials (encrypted)",
                             variable=app.save_credentials_var, bg=colors['bg_card'],
                             fg=colors['text_secondary'], selectcolor=colors['bg_card'])
    save_cb.grid(row=3, column=1, sticky='w', padx=5, pady=5)

    btn_frame2 = tk.Frame(remote_frame, bg=colors['bg_card'])
    btn_frame2.pack(pady=10)
    app.connect_remote_btn = ModernUI.create_animated_button(btn_frame2, "🔑 Connect to Broker",
                                                             app.connect_remote_mt5, 'success')
    app.connect_remote_btn.pack(side=tk.LEFT, padx=5)

    # Saved Connections Tab
    saved_frame = tk.Frame(notebook, bg=colors['bg_card'])
    notebook.add(saved_frame, text="Saved Connections")

    app.saved_connections_listbox = tk.Listbox(saved_frame, height=4, bg=colors['bg_sidebar'],
                                               fg=colors['text_primary'], selectbackground=colors['hover'],
                                               bd=0, font=('Segoe UI', 10))
    app.saved_connections_listbox.pack(fill=tk.X, padx=10, pady=10)

    btn_frame3 = tk.Frame(saved_frame, bg=colors['bg_card'])
    btn_frame3.pack(pady=5)
    app.load_saved_btn = ModernUI.create_animated_button(btn_frame3, "Load Selected",
                                                         app.load_saved_connection, 'info')
    app.load_saved_btn.pack(side=tk.LEFT, padx=5)
    app.delete_saved_btn = ModernUI.create_animated_button(btn_frame3, "Delete Selected",
                                                           app.delete_saved_connection, 'danger')
    app.delete_saved_btn.pack(side=tk.LEFT, padx=5)

    test_frame = tk.Frame(broker_card.content, bg=colors['bg_card'])
    test_frame.pack(pady=5)
    app.test_connection_btn = ModernUI.create_animated_button(test_frame, "🔄 Test Connection",
                                                              app.test_mt5_connection, 'info')
    app.test_connection_btn.pack()

    account_frame = tk.LabelFrame(broker_card.content, text="Account Information",
                                  font=('Segoe UI', 10, 'bold'), bg=colors['bg_card'], fg=colors['text_primary'])
    account_frame.pack(fill=tk.X, padx=10, pady=10)

    info_grid = tk.Frame(account_frame, bg=colors['bg_card'])
    info_grid.pack(padx=10, pady=10)

    account_info = [
        ("Balance:", "broker_balance", "$0.00"),
        ("Equity:", "broker_equity", "$0.00"),
        ("Margin:", "broker_margin", "$0.00"),
        ("Free Margin:", "broker_free_margin", "$0.00"),
        ("Server:", "broker_server_info", "Not connected"),
        ("Terminal:", "broker_terminal", "Not connected"),
    ]

    for i, (label, attr, default) in enumerate(account_info):
        row = i // 2
        col = i % 2
        tk.Label(info_grid, text=label, fg=colors['text_secondary'], bg=colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=row, column=col*2, sticky='w', padx=10, pady=2)
        value_label = tk.Label(info_grid, text=default, fg=colors['text_primary'], bg=colors['bg_card'],
                               font=('Segoe UI', 10, 'bold'))
        value_label.grid(row=row, column=col*2+1, sticky='w', padx=10, pady=2)
        setattr(app, attr, value_label)

    # Terminal Path
    path_frame = tk.Frame(broker_card.content, bg=colors['bg_card'])
    path_frame.pack(fill=tk.X, padx=10, pady=5)
    tk.Label(path_frame, text="MT5 Terminal Path:", fg=colors['text_secondary'],
             bg=colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT)
    app.mt5_path = tk.Entry(path_frame, width=50, bg=colors['bg_sidebar'], fg=colors['text_primary'],
                            bd=0, font=('Segoe UI', 10))
    app.mt5_path.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
    detect_btn = ModernUI.create_animated_button(path_frame, "🔍 Auto-detect", app.detect_mt5_path, 'info')
    detect_btn.pack(side=tk.LEFT, padx=5)
    browse_btn = ModernUI.create_animated_button(path_frame, "📁 Browse", app.browse_mt5_path, 'primary')
    browse_btn.pack(side=tk.LEFT)

    # Trading Settings Card
    settings_card = ModernCard(frame, title="Trading Settings")
    settings_card.pack(fill=tk.X, padx=20, pady=10)

    symbol_frame = tk.Frame(settings_card.content, bg=colors['bg_card'])
    symbol_frame.pack(fill=tk.X, padx=10, pady=10)
    tk.Label(symbol_frame, text="Symbol:", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)
    app.symbol_var = tk.StringVar()
    app.symbol_combo = ttk.Combobox(symbol_frame, textvariable=app.symbol_var, values=[], width=20,
                                    font=('Segoe UI', 11))
    app.symbol_combo.pack(side=tk.LEFT, padx=5)
    app.symbol_combo.bind('<KeyRelease>', app.on_symbol_search)
    change_btn = ModernUI.create_animated_button(symbol_frame, "Change", app.change_symbol, 'primary')
    change_btn.pack(side=tk.LEFT, padx=5)
    refresh_btn = ModernUI.create_animated_button(symbol_frame, "Refresh", app.refresh_symbols, 'info')
    refresh_btn.pack(side=tk.LEFT, padx=5)
    app.current_symbol_label = tk.Label(symbol_frame, text="", fg=colors['accent_success'],
                                        bg=colors['bg_card'], font=('Segoe UI', 11, 'bold'))
    app.current_symbol_label.pack(side=tk.LEFT, padx=10)

    # Stop Loss & Take Profit (Global)
    sltp_frame = tk.LabelFrame(settings_card.content, text="Stop Loss & Take Profit (Global)",
                               font=('Segoe UI', 11, 'bold'), bg=colors['bg_card'], fg=colors['text_primary'])
    sltp_frame.pack(fill=tk.X, padx=10, pady=10)

    grid_frame = tk.Frame(sltp_frame, bg=colors['bg_card'])
    grid_frame.pack(padx=10, pady=10)

    tk.Label(grid_frame, text="Stop Loss (pips):", fg=colors['text_secondary'],
             bg=colors['bg_card'], font=('Segoe UI', 11)).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.sl_pips_entry = tk.Entry(grid_frame, width=15, bg=colors['bg_sidebar'],
                                 fg=colors['text_primary'], insertbackground=colors['text_primary'],
                                 bd=0, font=('Segoe UI', 11))
    app.sl_pips_entry.grid(row=0, column=1, padx=5, pady=5)
    app.sl_pips_entry.insert(0, str(app.config.stop_loss_pips))

    tk.Label(grid_frame, text="Take Profit (pips):", fg=colors['text_secondary'],
             bg=colors['bg_card'], font=('Segoe UI', 11)).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.tp_pips_entry = tk.Entry(grid_frame, width=15, bg=colors['bg_sidebar'],
                                 fg=colors['text_primary'], insertbackground=colors['text_primary'],
                                 bd=0, font=('Segoe UI', 11))
    app.tp_pips_entry.grid(row=1, column=1, padx=5, pady=5)
    app.tp_pips_entry.insert(0, str(app.config.take_profit_pips))

    app.enable_sl_var = tk.BooleanVar(value=app.config.enable_stop_loss)
    app.enable_tp_var = tk.BooleanVar(value=app.config.enable_take_profit)
    enable_sl_cb = tk.Checkbutton(sltp_frame, text="Enable Stop Loss", variable=app.enable_sl_var,
                                  bg=colors['bg_card'], fg=colors['text_primary'], selectcolor=colors['bg_card'])
    enable_sl_cb.pack(anchor='w', padx=15)
    enable_tp_cb = tk.Checkbutton(sltp_frame, text="Enable Take Profit", variable=app.enable_tp_var,
                                  bg=colors['bg_card'], fg=colors['text_primary'], selectcolor=colors['bg_card'])
    enable_tp_cb.pack(anchor='w', padx=15)

    toggle_frame = tk.Frame(settings_card.content, bg=colors['bg_card'])
    toggle_frame.pack(padx=10, pady=10)
    app.close_opposite_var = tk.BooleanVar(value=app.config.close_opposite_on_signal_change)
    close_opposite_cb = tk.Checkbutton(toggle_frame, text="Close Opposite on Signal",
                                       variable=app.close_opposite_var, bg=colors['bg_card'],
                                       fg=colors['text_primary'], selectcolor=colors['bg_card'])
    close_opposite_cb.grid(row=0, column=0, padx=10)

    # Reversal Settings (without SL/TP)
    reversal_frame = tk.LabelFrame(settings_card.content, text="⚡ SIGNAL REVERSAL TRADING (11 CONFIRMATIONS)",
                                   font=('Montserrat', 12, 'bold'), bg=colors['bg_card'], fg=colors['accent_warning'])
    reversal_frame.pack(fill=tk.X, padx=10, pady=10)

    reversal_grid = tk.Frame(reversal_frame, bg=colors['bg_card'])
    reversal_grid.pack(padx=10, pady=10)

    reversal_settings = [
        ('Reversal Lot Size:', 'reversal_lot_size', '0.01'),
        ('Min Confidence (%):', 'reversal_min_conf', '70'),
        ('Cooldown (seconds):', 'reversal_cooldown', '300'),
    ]

    for i, (label, attr, default) in enumerate(reversal_settings):
        tk.Label(reversal_grid, text=label, fg=colors['text_secondary'], bg=colors['bg_card'],
                 font=('Segoe UI', 11)).grid(row=i, column=0, sticky='w', padx=5, pady=5)
        entry = tk.Entry(reversal_grid, width=15, bg=colors['bg_sidebar'], fg=colors['text_primary'],
                         insertbackground=colors['text_primary'], bd=0, font=('Segoe UI', 11))
        entry.grid(row=i, column=1, padx=5, pady=5)
        entry.insert(0, default)
        setattr(app, attr, entry)

    note_label = tk.Label(reversal_frame,
                          text="ℹ️ Reversal trades use the global Stop Loss and Take Profit settings above.",
                          fg=colors['text_secondary'], bg=colors['bg_card'], wraplength=600, justify=tk.LEFT,
                          font=('Segoe UI', 10))
    note_label.pack(padx=10, pady=(0,10))

    save_btn = ModernUI.create_animated_button(settings_card.content, "Save Settings", app.save_settings, 'success')
    save_btn.pack(pady=10)

    # Counter Controls
    counter_card = ModernCard(frame, title="Counter Controls")
    counter_card.pack(fill=tk.X, padx=20, pady=10)

    reset_signal_btn = ModernUI.create_animated_button(counter_card.content, "Reset Signal Counter",
                                                       app.reset_signal_counter, 'warning')
    reset_signal_btn.pack(side=tk.LEFT, padx=10, pady=10)
    reset_session_btn = ModernUI.create_animated_button(counter_card.content, "Reset Session Counter",
                                                        app.reset_session_counter, 'warning')
    reset_session_btn.pack(side=tk.LEFT, padx=10, pady=10)

    return frame


def create_trailing_section(parent, colors, app):
    """Create the trailing stop section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    config_card = ModernCard(frame, title="Step Trailing Configuration")
    config_card.pack(fill=tk.X, padx=20, pady=10)

    toggle_frame = tk.Frame(config_card.content, bg=colors['bg_card'])
    toggle_frame.pack(padx=10, pady=10)
    tk.Label(toggle_frame, text="Enable Trailing Stop:", fg=colors['text_secondary'],
             bg=colors['bg_card'], font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)
    app.trailing_var = tk.BooleanVar(value=False)
    trailing_check = tk.Checkbutton(toggle_frame, variable=app.trailing_var, bg=colors['bg_card'],
                                    fg=colors['accent_success'], selectcolor=colors['bg_card'])
    trailing_check.pack(side=tk.LEFT)

    grid_frame = tk.Frame(config_card.content, bg=colors['bg_card'])
    grid_frame.pack(padx=10, pady=10)

    settings = [
        ('Lock Amount ($):', 'lock_amount_entry', '3.0'),
        ('Step Amount ($):', 'step_amount_entry', '4.0'),
    ]

    for i, (label, attr, default) in enumerate(settings):
        tk.Label(grid_frame, text=label, fg=colors['text_secondary'], bg=colors['bg_card'],
                 font=('Segoe UI', 11)).grid(row=i, column=0, sticky='w', padx=5, pady=5)
        entry = tk.Entry(grid_frame, width=15, bg=colors['bg_sidebar'], fg=colors['text_primary'],
                         insertbackground=colors['text_primary'], bd=0, font=('Segoe UI', 11))
        entry.grid(row=i, column=1, padx=5, pady=5)
        entry.insert(0, default)
        setattr(app, attr, entry)

    btn_frame = tk.Frame(config_card.content, bg=colors['bg_card'])
    btn_frame.pack(pady=10)
    update_btn = ModernUI.create_animated_button(btn_frame, "Update Config", app.update_trailing_config, 'primary')
    update_btn.pack(side=tk.LEFT, padx=5)
    apply_btn = ModernUI.create_animated_button(btn_frame, "Apply to All", app.apply_trailing_all, 'info')
    apply_btn.pack(side=tk.LEFT, padx=5)
    refresh_btn = ModernUI.create_animated_button(btn_frame, "Refresh Stats", app.refresh_trailing_stats, 'success')
    refresh_btn.pack(side=tk.LEFT, padx=5)

    stats_card = ModernCard(frame, title="Trailing Performance")
    stats_card.pack(fill=tk.X, padx=20, pady=10)

    app.trailing_stats_grid = tk.Frame(stats_card.content, bg=colors['bg_card'])
    app.trailing_stats_grid.pack(fill=tk.X, padx=10, pady=10)

    app.trailing_stats = {}
    stats = [
        ('Managed Positions', 'managed_positions', '0'),
        ('Win Rate', 'trailing_win_rate', '0%'),
        ('Total Profit', 'trailing_profit', '$0.00'),
        ('Profit Factor', 'trailing_profit_factor', '0.00')
    ]

    for i, (label, key, default) in enumerate(stats):
        stat_frame = tk.Frame(app.trailing_stats_grid, bg=colors['bg_card'])
        stat_frame.grid(row=0, column=i, padx=5, pady=5, sticky='nsew')
        app.trailing_stats_grid.grid_columnconfigure(i, weight=1)
        tk.Label(stat_frame, text=label, fg=colors['text_secondary'], bg=colors['bg_card'],
                 font=('Segoe UI', 10)).pack(pady=(10,5))
        value_label = tk.Label(stat_frame, text=default, font=('Montserrat', 14, 'bold'),
                               fg=colors['text_primary'], bg=colors['bg_card'])
        value_label.pack(pady=(0,10))
        app.trailing_stats[key] = value_label

    positions_frame = tk.LabelFrame(frame, text="Managed Positions Details",
                                    font=('Montserrat', 12, 'bold'), bg=colors['bg_dark'], fg=colors['text_primary'])
    positions_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    columns = ('Ticket', 'Symbol', 'Type', 'P&L', 'Locked', 'At Risk', 'Stop Loss')
    app.trailing_positions_tree = ttk.Treeview(positions_frame, columns=columns, show='headings', height=8)
    for col in columns:
        app.trailing_positions_tree.heading(col, text=col)
        app.trailing_positions_tree.column(col, width=100)
    app.trailing_positions_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar = ttk.Scrollbar(positions_frame, orient="vertical", command=app.trailing_positions_tree.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.trailing_positions_tree.configure(yscrollcommand=scrollbar.set)

    return frame


def create_alerts_section(parent, colors, app):
    """Create the alerts section."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    config_card = ModernCard(frame, title="Alert System Configuration")
    config_card.pack(fill=tk.X, padx=20, pady=10)

    toggle_frame = tk.Frame(config_card.content, bg=colors['bg_card'])
    toggle_frame.pack(padx=10, pady=10)
    tk.Label(toggle_frame, text="Enable Sound Alerts:", fg=colors['text_secondary'],
             bg=colors['bg_card'], font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)
    app.alerts_var = tk.BooleanVar(value=True)
    alerts_check = tk.Checkbutton(toggle_frame, variable=app.alerts_var, bg=colors['bg_card'],
                                  fg=colors['accent_success'], selectcolor=colors['bg_card'],
                                  command=app.toggle_alerts)
    alerts_check.pack(side=tk.LEFT)

    types_frame = tk.Frame(config_card.content, bg=colors['bg_card'])
    types_frame.pack(padx=10, pady=10)

    alert_types = [
        ('BUY Signal', 'High beep (800Hz) x2', colors['accent_success']),
        ('SELL Signal', 'Low beep (400Hz) x2', colors['accent_danger']),
        ('Signal Reversal', 'Triple beep (1000Hz) x3', colors['accent_warning']),
        ('Reversal Confirmed', '5 quick beeps (1200Hz)', colors['accent_success']),
        ('Reversal Skipped', 'Double low beep (600Hz)', colors['accent_warning']),
        ('Overbought', 'Warning beep (600Hz) x2', colors['accent_warning']),
        ('Oversold', 'Warning beep (600Hz) x2', colors['accent_warning']),
        ('Trade Execution', 'Quick click (1200Hz) x1', colors['accent_info']),
        ('Stop Loss Hit', 'Long low (200Hz) x2', colors['accent_danger']),
        ('Take Profit Hit', 'Celebration (1500Hz) x3', colors['accent_success']),
    ]

    for i, (title, desc, color) in enumerate(alert_types):
        row = i // 2
        col = i % 2
        item_frame = tk.Frame(types_frame, bg=colors['bg_sidebar'])
        item_frame.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
        types_frame.grid_columnconfigure(col, weight=1)
        tk.Label(item_frame, text=title, fg=color, font=('Segoe UI', 11, 'bold'),
                 bg=colors['bg_sidebar']).pack(anchor='w', padx=10, pady=(5,0))
        tk.Label(item_frame, text=desc, fg=colors['text_secondary'], font=('Segoe UI', 10),
                 bg=colors['bg_sidebar']).pack(anchor='w', padx=10, pady=(0,5))

    test_btn = ModernUI.create_animated_button(config_card.content, "Test All Alerts", app.test_alerts, 'primary')
    test_btn.pack(pady=10)

    return frame

def create_reversal_section(parent, colors, app):
    """Create the reversal statistics section with toggleable indicators."""
    frame = tk.Frame(parent, bg=colors['bg_dark'])

    header_frame = tk.Frame(frame, bg=colors['bg_dark'])
    header_frame.pack(fill=tk.X, padx=20, pady=10)

    tk.Label(header_frame, text="⚡ REVERSAL TRADING STATISTICS",
             font=('Montserrat', 16, 'bold'), fg=colors['text_primary'], bg=colors['bg_dark']).pack(side=tk.LEFT)

    refresh_btn = ModernUI.create_animated_button(header_frame, "Refresh", app.refresh_reversal_stats, 'info')
    refresh_btn.pack(side=tk.RIGHT)

    # Summary cards
    summary_frame = tk.Frame(frame, bg=colors['bg_dark'])
    summary_frame.pack(fill=tk.X, padx=20, pady=10)

    cards = [
        ('Total Reversals', 'total_reversals_val', '0', colors['accent_info']),
        ('Executed', 'executed_reversals_val', '0', colors['accent_success']),
        ('Skipped', 'skipped_reversals_val', '0', colors['accent_warning']),
        ('Avg Confidence', 'avg_confidence_val', '0%', colors['accent_primary']),
    ]

    for i, (label, var, default, color) in enumerate(cards):
        card = ModernCard(summary_frame, width=200)
        card.grid(row=0, column=i, padx=5, sticky='nsew')
        summary_frame.grid_columnconfigure(i, weight=1)

        tk.Label(card.content, text=label, font=('Segoe UI', 11),
                 fg=colors['text_secondary'], bg=colors['bg_card']).pack(pady=(5,0))
        value_label = tk.Label(card.content, text=default, font=('Montserrat', 20, 'bold'),
                               fg=color, bg=colors['bg_card'])
        value_label.pack(pady=(0,10))
        setattr(app, var, value_label)

    # Confidence meter
    meter_card = ModernCard(frame, title="Current Confidence Threshold")
    meter_card.pack(fill=tk.X, padx=20, pady=10)

    meter_frame = tk.Frame(meter_card.content, bg=colors['bg_card'])
    meter_frame.pack(pady=10)

    tk.Label(meter_frame, text="Min Confidence:", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=5)

    app.reversal_min_conf_var = tk.StringVar(value=str(app.config.reversal_min_confidence_score))
    min_conf_spin = tk.Spinbox(meter_frame, from_=0, to=100, textvariable=app.reversal_min_conf_var,
                               width=5, bg=colors['bg_sidebar'], fg=colors['text_primary'], bd=0,
                               font=('Segoe UI', 11))
    min_conf_spin.pack(side=tk.LEFT, padx=5)
    min_conf_spin.bind('<KeyRelease>', app.update_reversal_confidence)

    tk.Label(meter_frame, text="%", fg=colors['text_secondary'], bg=colors['bg_card'],
             font=('Segoe UI', 11)).pack(side=tk.LEFT)

    app.reversal_meter = AnimatedProgressBar(meter_frame, width=300, height=15,
                                             fg_color=colors['accent_success'])
    app.reversal_meter.pack(side=tk.LEFT, padx=20)

    # ========== INDICATORS AS TOGGLE BUTTONS ==========
    indicators_card = ModernCard(frame, title="11 Confirmation Indicators (Click to Toggle)")
    indicators_card.pack(fill=tk.X, padx=20, pady=10)

    app.indicator_buttons = {}
    indicators_grid = tk.Frame(indicators_card.content, bg=colors['bg_card'])
    indicators_grid.pack(padx=10, pady=10)

    # List of (display_name, config_key)
    indicators = [
        ("1. Price Retest", "reversal_require_retest"),
        ("2. Volatility", "reversal_use_volatility_filter"),
        ("3. Volume Spike", "reversal_require_volume_spike"),
        ("4. Momentum", "reversal_use_momentum_filter"),
        ("5. S/R Level", "reversal_check_support_resistance"),
        ("6. News Filter", "reversal_avoid_high_impact_news"),
        ("7. Time Filter", "reversal_use_time_filter"),   # add this config key if missing
        ("8. Higher TF", "reversal_require_higher_tf_alignment"),
        ("9. Pattern", "reversal_require_pattern"),
        ("10. Fibonacci", "reversal_use_fibonacci"),
        ("11. Trendline/SR", "reversal_use_trendline_sr"),
    ]

    for i, (label, config_key) in enumerate(indicators):
        row = i // 2
        col = i % 2
        btn_frame = tk.Frame(indicators_grid, bg=colors['bg_sidebar'], relief=tk.RAISED, bd=1)
        btn_frame.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
        indicators_grid.grid_columnconfigure(col, weight=1)

        # Get current state from config (default to True if missing)
        current_state = getattr(app.config, config_key, True)
        btn_text = f"{label}\n{'✅ ACTIVE' if current_state else '❌ INACTIVE'}"
        btn_bg = colors['accent_success'] if current_state else colors['accent_danger']

        btn = tk.Button(
            btn_frame,
            text=btn_text,
            bg=btn_bg,
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            padx=10,
            pady=5,
            cursor='hand2'
        )
        btn.pack(fill=tk.BOTH, expand=True)
        # Bind command with current config_key and button reference
        btn.config(command=lambda k=config_key, b=btn: app.toggle_reversal_indicator(k, b))
        app.indicator_buttons[config_key] = btn
        # Also store as attribute for potential updates
        setattr(app, f"{config_key}_btn", btn)

    # ========== REVERSAL HISTORY ==========
    history_card = ModernCard(frame, title="Reversal History")
    history_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    columns = ('Time', 'From', 'To', 'Confidence', 'Result', 'Passed Checks')
    app.reversal_history_tree = ttk.Treeview(history_card.content, columns=columns, show='headings', height=8)
    for col in columns:
        app.reversal_history_tree.heading(col, text=col)
        app.reversal_history_tree.column(columns[-1], width=250) 
    app.reversal_history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar = ttk.Scrollbar(history_card.content, orient="vertical", command=app.reversal_history_tree.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    app.reversal_history_tree.configure(yscrollcommand=scrollbar.set)

    return frame