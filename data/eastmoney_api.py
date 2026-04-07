# data/eastmoney_api.py（从断点继续，这是完整文件的后半段）
# ========= 接上文 get_margin_data_stock 之后 =========

    def get_margin_ranking(self, indicator: str = "rz_buy",
                            page_size: int = 100) -> pd.DataFrame:
        """
        融资融券变动排名
        indicator: rz_buy=融资买入 rq_sell=融券卖出
        """
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"

        sort_map = {
            "rz_buy": "RZMRE",
            "rz_balance": "RZYE",
            "rq_sell": "RQMCL",
            "rq_balance": "RQYE",
            "rq_volume": "RQYL",
        }

        params = {
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": sort_map.get(indicator, "RZMRE"),
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": page_size,
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "TRADE_DATE": "trade_date",
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "RZYE": "rz_balance",
            "RZMRE": "rz_buy",
            "RZCHE": "rz_repay",
            "RQYE": "rq_balance",
            "RQYL": "rq_volume",
            "RQMCL": "rq_sell_volume",
            "RQCHL": "rq_return_volume",
            "RZRQYE": "total_balance",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ====================== 公告数据 ======================

    def get_announcements(self, stock_code: str = None,
                           start_date: str = None,
                           end_date: str = None,
                           page_size: int = 100) -> pd.DataFrame:
        """获取上市公司公告"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_index": 1,
            "page_size": page_size,
            "ann_type": "A",
            "client_source": "web",
            "f_node": "0",
            "s_node": "0",
            "begin_time": start_date,
            "end_time": end_date,
        }
        if stock_code:
            params["stock_list"] = stock_code

        try:
            resp = self.session.get(url, params=params, timeout=10)
            data = resp.json()
            if not data or "data" not in data:
                return pd.DataFrame()

            items = data["data"].get("list", [])
            records = []
            for item in items:
                records.append({
                    "ann_date": item.get("notice_date", ""),
                    "stock_code": item.get("codes", [{}])[0].get("stock_code", "") if item.get("codes") else "",
                    "stock_name": item.get("codes", [{}])[0].get("short_name", "") if item.get("codes") else "",
                    "title": item.get("title", ""),
                    "ann_type": item.get("columns", [{}])[0].get("column_name", "") if item.get("columns") else "",
                })
            return pd.DataFrame(records)
        except Exception as e:
            return pd.DataFrame()

    # ====================== 板块资金流 ======================

    def get_sector_fund_flow(self, sector_type: str = "concept",
                              page_size: int = 100) -> pd.DataFrame:
        """板块资金流向排名"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fs_map = {
            "concept": "m:90+t:3+f:!50",
            "industry": "m:90+t:2+f:!50"
        }
        params = {
            "cb": "jQuery_cb",
            "pn": 1, "pz": page_size,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2,
            "fid": "f62",
            "fs": fs_map.get(sector_type, fs_map["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124",
        }
        data = self._request(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()

        records = data["data"].get("diff", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "f12": "board_code", "f14": "board_name",
            "f2": "latest_price", "f3": "change_pct",
            "f62": "main_net_inflow",
            "f184": "main_net_inflow_pct",
            "f66": "super_large_inflow",
            "f69": "super_large_inflow_pct",
            "f72": "large_inflow",
            "f75": "large_inflow_pct",
            "f78": "medium_inflow",
            "f81": "medium_inflow_pct",
            "f84": "small_inflow",
            "f87": "small_inflow_pct",
        }
        df = df.rename(columns=col_map)

        money_cols = ["main_net_inflow", "super_large_inflow", "large_inflow",
                      "medium_inflow", "small_inflow"]
        for col in money_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce") / 1e8  # 转亿元

        df["board_type"] = sector_type
        return df

    # ====================== 板块成分股 ======================

    def get_board_constituents(self, board_code: str,
                                board_type: str = "concept") -> pd.DataFrame:
        """获取板块成分股"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"

        if board_type == "concept":
            fs = f"b:{board_code}+f:!50"
        else:
            fs = f"b:{board_code}+f:!50"

        params = {
            "cb": "jQuery_cb",
            "pn": 1, "pz": 300,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2,
            "fid": "f3",
            "fs": fs,
            "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18",
        }
        data = self._request(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()

        records = data["data"].get("diff", [])
        df = pd.DataFrame(records)
        col_map = {
            "f12": "stock_code", "f14": "stock_name",
            "f2": "latest_price", "f3": "change_pct",
            "f5": "volume", "f6": "amount",
            "f7": "amplitude", "f8": "turnover_rate",
            "f15": "high", "f16": "low",
            "f17": "open", "f18": "pre_close",
        }
        df = df.rename(columns=col_map)
        return df

    # ====================== 涨停池 ======================

    def get_limit_up_pool(self, date: str = None) -> pd.DataFrame:
        """获取涨停股池"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_LIMITUP_BASICINFOS",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "FIRST_LIMIT_TIME",
            "sortTypes": "1",
            "pageNumber": 1,
            "pageSize": 300,
            "filter": f"(TRADE_DATE='{date}')",
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "TRADE_DATE": "trade_date",
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "CLOSE_PRICE": "close_price",
            "CHANGE_RATE": "change_pct",
            "FIRST_LIMIT_TIME": "first_limit_time",
            "LAST_LIMIT_TIME": "last_limit_time",
            "LIMIT_UP_DAYS": "limit_up_days",       # 连板天数
            "OPEN_TIMES": "open_times",              # 开板次数
            "TURNOVERRATE": "turnover_rate",
            "FREE_MARKET_CAP": "free_mv",
            "INDUSTRY": "industry",
            "RELATED_PLATE": "related_concept",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df


# 全局单例
api = EastMoneyAPI()
