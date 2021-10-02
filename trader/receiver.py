import os
import sys
import time
import psutil
import pythoncom
from PyQt5 import QtWidgets
from PyQt5.QtCore import QTimer
from PyQt5.QAxContainer import QAxWidget
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from utility.static import *
from utility.setting import *


class Receiver:
    app = QtWidgets.QApplication(sys.argv)

    def __init__(self, windowQ, receivQ, stgQ, queryQ, tick1Q, tick2Q, tick3Q, tick4Q):
        self.windowQ = windowQ
        self.receivQ = receivQ
        self.stgQ = stgQ
        self.queryQ = queryQ
        self.tick1Q = tick1Q
        self.tick2Q = tick2Q
        self.tick3Q = tick3Q
        self.tick4Q = tick4Q

        self.dict_bool = {
            '실시간조건검색시작': False,
            '실시간조건검색중단': False,
            '장중단타전략시작': False,

            '로그인': False,
            'TR수신': False,
            'TR다음': False,
            'CD수신': False,
            'CR수신': False
        }
        self.dict_time = {
            '거래대금순위': now(),
            '부가정보': now()
        }
        self.dict_intg = {
            '스레드': 0,
            '시피유': 0.,
            '메모리': 0.
        }
        self.dict_gsjm = {}
        self.dict_cdjm = {}
        self.dict_vipr = {}
        self.dict_tick = {}
        self.dict_hoga = {}
        self.dict_cond = {}
        self.name_code = {}

        self.list_gsjm = []
        self.list_trcd = []
        self.list_jang = []
        self.pre_top = []
        self.list_kosd = None
        self.list_code = None
        self.list_code1 = None
        self.list_code2 = None
        self.list_code3 = None
        self.list_code4 = None

        self.df_tr = None
        self.dict_item = None
        self.str_tname = None

        self.operation = 1
        self.df_mt = pd.DataFrame(columns=['거래대금순위'])
        self.df_mc = pd.DataFrame(columns=['최근거래대금'])
        self.str_tday = strf_time('%Y%m%d')
        self.str_jcct = self.str_tday + '090000'

        remaintime = (strp_time('%Y%m%d%H%M%S', self.str_tday + '090100') - now()).total_seconds()
        exittime = timedelta_sec(remaintime) if remaintime > 0 else timedelta_sec(600)
        self.exit_time = exittime
        self.time_mtop = now()

        self.timer = QTimer()
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self.ConditionInsertDelete)

        self.ocx = QAxWidget('KHOPENAPI.KHOpenAPICtrl.1')
        self.ocx.OnEventConnect.connect(self.OnEventConnect)
        self.ocx.OnReceiveTrData.connect(self.OnReceiveTrData)
        self.ocx.OnReceiveRealData.connect(self.OnReceiveRealData)
        self.ocx.OnReceiveTrCondition.connect(self.OnReceiveTrCondition)
        self.ocx.OnReceiveConditionVer.connect(self.OnReceiveConditionVer)
        self.ocx.OnReceiveRealCondition.connect(self.OnReceiveRealCondition)
        self.Start()

    def Start(self):
        self.CommConnect()
        self.EventLoop()

    def CommConnect(self):
        self.ocx.dynamicCall('CommConnect()')
        while not self.dict_bool['로그인']:
            pythoncom.PumpWaitingMessages()

        self.dict_bool['CD수신'] = False
        self.ocx.dynamicCall('GetConditionLoad()')
        while not self.dict_bool['CD수신']:
            pythoncom.PumpWaitingMessages()

        self.list_kosd = self.GetCodeListByMarket('10')
        list_code = self.GetCodeListByMarket('0') + self.list_kosd
        df = pd.DataFrame(columns=['종목명'])
        for code in list_code:
            name = self.GetMasterCodeName(code)
            df.at[code] = name
            self.name_code[name] = code

        self.queryQ.put([2, df, 'codename', 'replace'])

        data = self.ocx.dynamicCall('GetConditionNameList()')
        conditions = data.split(';')[:-1]
        for condition in conditions:
            cond_index, cond_name = condition.split('^')
            self.dict_cond[int(cond_index)] = cond_name

    def EventLoop(self):
        self.OperationRealreg()
        self.ViRealreg()
        while True:
            if not self.receivQ.empty():
                work = self.receivQ.get()
                if type(work) == list:
                    self.UpdateRealreg(work)
                elif type(work) == str:
                    self.UpdateJangolist(work)
                continue

            if self.operation == 1 and now() > self.exit_time:
                break

            if self.operation == 3:
                if int(strf_time('%H%M%S')) < 10000:
                    if not self.dict_bool['실시간조건검색시작']:
                        self.ConditionSearchStart()
                if 10000 <= int(strf_time('%H%M%S')):
                    if self.dict_bool['실시간조건검색시작'] and not self.dict_bool['실시간조건검색중단']:
                        self.ConditionSearchStop()
                    if not self.dict_bool['장중단타전략시작']:
                        self.StartJangjungStrategy()
            if self.operation == 8:
                self.ALlRemoveRealreg()
                self.SaveDatabase()
                break

            if now() > self.dict_time['거래대금순위']:
                if len(self.df_mt):
                    self.UpdateMoneyTop()
                self.dict_time['거래대금순위'] = timedelta_sec(1)
            if now() > self.dict_time['부가정보']:
                self.UpdateInfo()
                self.dict_time['부가정보'] = timedelta_sec(2)

            time_loop = timedelta_sec(0.25)
            while now() < time_loop:
                pythoncom.PumpWaitingMessages()
                time.sleep(0.0001)

        self.windowQ.put([1, '시스템 명령 실행 알림 - 리시버 종료'])

    def UpdateRealreg(self, rreg):
        sn = rreg[0]
        if len(rreg) == 2:
            self.ocx.dynamicCall('SetRealRemove(QString, QString)', rreg)
            self.windowQ.put([1, f'실시간 알림 중단 완료 - 모든 실시간 데이터 수신 중단'])
        elif len(rreg) == 4:
            ret = self.ocx.dynamicCall('SetRealReg(QString, QString, QString, QString)', rreg)
            result = '완료' if ret == 0 else '실패'
            if sn == sn_oper:
                self.windowQ.put([1, f'실시간 알림 등록 {result} - 장운영시간 [{sn}]'])
            else:
                self.windowQ.put([1, f"실시간 알림 등록 {result} - [{sn}] 종목갯수 {len(rreg[1].split(';'))}"])

    def UpdateJangolist(self, work):
        code = work.split(' ')[1]
        if '잔고편입' in work and code not in self.list_jang:
            self.list_jang.append(code)
            if code not in self.dict_gsjm.keys():
                self.dict_gsjm[code] = '090000'
                self.stgQ.put(['조건진입', code])
        elif '잔고청산' in work and code in self.list_jang:
            self.list_jang.remove(code)
            if code not in self.list_gsjm and code in self.dict_gsjm.keys():
                self.stgQ.put(['조건이탈', code])
                del self.dict_gsjm[code]

    def OperationRealreg(self):
        self.receivQ.put([sn_oper, ' ', '215;20;214', 0])
        self.list_code = self.SendCondition(sn_oper, self.dict_cond[1], 1, 0)
        self.list_code1 = [code for i, code in enumerate(self.list_code) if i % 4 == 0]
        self.list_code2 = [code for i, code in enumerate(self.list_code) if i % 4 == 1]
        self.list_code3 = [code for i, code in enumerate(self.list_code) if i % 4 == 2]
        self.list_code4 = [code for i, code in enumerate(self.list_code) if i % 4 == 3]
        k = 0
        for i in range(0, len(self.list_code), 100):
            self.receivQ.put([sn_jchj + k, ';'.join(self.list_code[i:i + 100]), '10;12;14;30;228;41;61;71;81', 1])
            k += 1

    def ViRealreg(self):
        self.Block_Request('opt10054', 시장구분='000', 장전구분='1', 종목코드='', 발동구분='1', 제외종목='111111011',
                           거래량구분='0', 거래대금구분='0', 발동방향='0', output='발동종목', next=0)
        self.windowQ.put([1, '시스템 명령 실행 알림 - 콜렉터 시작 완료'])

    def ConditionSearchStart(self):
        self.dict_bool['실시간조건검색시작'] = True
        self.windowQ.put([2, '실시간 조건검색식 등록'])
        codes = self.SendCondition(sn_cond, self.dict_cond[0], 0, 1)
        self.df_mt.at[self.str_tday + '090000'] = ';'.join(codes)
        if len(codes) > 0:
            for code in codes:
                self.list_gsjm.append(code)
                self.dict_gsjm[code] = '090000'
                self.stgQ.put(['조건진입', code])
        self.windowQ.put([1, '시스템 명령 실행 알림 - 실시간조건검색 등록 완료'])

    def ConditionSearchStop(self):
        self.dict_bool['실시간조건검색중단'] = True
        self.ocx.dynamicCall("SendConditionStop(QString, QString, int)", sn_cond, self.dict_cond[0], 0)
        self.windowQ.put([1, '시스템 명령 실행 알림 - 실시간조건검색 중단 완료'])

    def StartJangjungStrategy(self):
        self.dict_bool['장중단타전략시작'] = True
        self.df_mc.sort_values(by=['최근거래대금'], ascending=False, inplace=True)
        list_top = list(self.df_mc.index[:30])
        insert_list = set(list_top) - set(self.list_gsjm)
        if len(insert_list) > 0:
            for code in list(insert_list):
                self.list_gsjm.append(code)
                if code not in self.list_jang and code not in self.dict_gsjm.keys():
                    self.stgQ.put(['조건진입', code])
                    self.dict_gsjm[code] = '090000'
        delete_list = set(self.list_gsjm) - set(list_top)
        if len(delete_list) > 0:
            for code in list(delete_list):
                self.list_gsjm.remove(code)
                if code not in self.list_jang and code in self.dict_gsjm.keys():
                    self.stgQ.put(['조건이탈', code])
                    del self.dict_gsjm[code]
        self.pre_top = list_top
        self.timer.start()

    def ConditionInsertDelete(self):
        self.df_mc.sort_values(by=['최근거래대금'], ascending=False, inplace=True)
        list_top = list(self.df_mc.index[:30])
        insert_list = set(list_top) - set(self.pre_top)
        if len(insert_list) > 0:
            for code in list(insert_list):
                if code not in self.list_gsjm:
                    self.list_gsjm.append(code)
                if code not in self.list_jang and code not in self.dict_gsjm.keys():
                    self.stgQ.put(['조건진입', code])
                    self.dict_gsjm[code] = '090000'
        delete_list = set(self.pre_top) - set(list_top)
        if len(delete_list) > 0:
            for code in list(delete_list):
                if code in self.list_gsjm:
                    self.list_gsjm.remove(code)
                if code not in self.list_jang and code in self.dict_gsjm.keys():
                    self.stgQ.put(['조건이탈', code])
                    del self.dict_gsjm[code]
        self.pre_top = list_top

    def ALlRemoveRealreg(self):
        self.dict_bool['실시간데이터수신중단'] = True
        self.windowQ.put([2, '실시간 데이터 수신 중단'])
        self.receivQ.put(['ALL', 'ALL'])
        self.windowQ.put([1, '시스템 명령 실행 알림 - 실시간 데이터 중단 완료'])

    def SaveDatabase(self):
        self.windowQ.put([2, '틱데이터 저장'])
        self.queryQ.put([2, self.df_mt, 'moneytop', 'append'])
        self.tick1Q.put('틱데이터저장')
        self.tick2Q.put('틱데이터저장')
        self.tick3Q.put('틱데이터저장')
        self.tick4Q.put('틱데이터저장')
        self.windowQ.put([1, '시스템 명령 실행 알림 - 틱데이터를 저장합니다.'])

    def UpdateMoneyTop(self):
        timetype = '%Y%m%d%H%M%S'
        list_text = ';'.join(self.list_gsjm)
        curr_time = self.str_jcct
        curr_datetime = strp_time(timetype, curr_time)
        last_datetime = strp_time(timetype, self.df_mt.index[-1])
        gap_seconds = (curr_datetime - last_datetime).total_seconds()
        while gap_seconds > 2:
            gap_seconds -= 1
            pre_time = strf_time(timetype, timedelta_sec(-gap_seconds, curr_datetime))
            self.df_mt.at[pre_time] = list_text
        self.df_mt.at[curr_time] = list_text

    @thread_decorator
    def UpdateInfo(self):
        info = [7, self.dict_intg['메모리'], self.dict_intg['스레드'], self.dict_intg['시피유']]
        self.windowQ.put(info)
        self.UpdateSysinfo()

    def UpdateSysinfo(self):
        p = psutil.Process(os.getpid())
        self.dict_intg['메모리'] = round(p.memory_info()[0] / 2 ** 20.86, 2)
        self.dict_intg['스레드'] = p.num_threads()
        self.dict_intg['시피유'] = round(p.cpu_percent(interval=2) / 2, 2)

    def OnEventConnect(self, err_code):
        if err_code == 0:
            self.dict_bool['로그인'] = True

    def OnReceiveConditionVer(self, ret, msg):
        if msg == '':
            return
        if ret == 1:
            self.dict_bool['CD수신'] = True

    def OnReceiveTrCondition(self, screen, code_list, cond_name, cond_index, nnext):
        if screen == "" and cond_name == "" and cond_index == "" and nnext == "":
            return
        codes = code_list.split(';')[:-1]
        self.list_trcd = codes
        self.dict_bool['CR수신'] = True

    def OnReceiveRealCondition(self, code, IorD, cname, cindex):
        if cname == '' and cindex == '':
            return
        if int(strf_time('%H%M%S')) > 100000:
            return

        if IorD == 'I':
            if code not in self.list_gsjm:
                self.list_gsjm.append(code)
            if code not in self.list_jang and code not in self.dict_gsjm.keys():
                self.stgQ.put(['조건진입', code])
                self.dict_gsjm[code] = '090000'
        elif IorD == 'D':
            if code in self.list_gsjm:
                self.list_gsjm.remove(code)
            if code not in self.list_jang and code in self.dict_gsjm.keys():
                self.stgQ.put(['조건이탈', code])
                del self.dict_gsjm[code]

    def OnReceiveRealData(self, code, realtype, realdata):
        if realdata == '':
            return

        if realtype == '장시작시간':
            try:
                self.operation = int(self.GetCommRealData(code, 215))
                current = self.GetCommRealData(code, 20)
                remain = self.GetCommRealData(code, 214)
            except Exception as e:
                self.windowQ.put([1, f'OnReceiveRealData 장시작시간 {e}'])
            else:
                self.windowQ.put([1, f'장운영 시간 수신 알림 - {self.operation} {current[:2]}:{current[2:4]}:{current[4:]} '
                                     f'남은시간 {remain[:2]}:{remain[2:4]}:{remain[4:]}'])
                if self.operation == 3:
                    self.windowQ.put([2, '장운영상태'])
        elif realtype == 'VI발동/해제':
            try:
                code = self.GetCommRealData(code, 9001).strip('A').strip('Q')
                gubun = self.GetCommRealData(code, 9068)
                name = self.GetMasterCodeName(code)
            except Exception as e:
                self.windowQ.put([1, f'OnReceiveRealData VI발동/해제 {e}'])
            else:
                if gubun == '1' and code in self.list_code and \
                        (code not in self.dict_vipr.keys() or
                         (self.dict_vipr[code][0] and now() > self.dict_vipr[code][1])):
                    self.UpdateViPriceDown5(code, name)
        elif realtype == '주식체결':
            try:
                c = abs(int(self.GetCommRealData(code, 10)))
                o = abs(int(self.GetCommRealData(code, 16)))
                v = int(self.GetCommRealData(code, 15))
                t = self.GetCommRealData(code, 20)
            except Exception as e:
                self.windowQ.put([1, f'OnReceiveRealData 주식체결 {e}'])
            else:
                if self.operation == 1:
                    self.operation = 3
                if t != self.str_jcct[8:]:
                    self.str_jcct = self.str_tday + t
                if code not in self.dict_vipr.keys():
                    self.InsertViPriceDown5(code, o)
                if code in self.dict_vipr.keys() and not self.dict_vipr[code][0] and now() > self.dict_vipr[code][1]:
                    self.UpdateViPriceDown5(code, c)
                try:
                    pret = self.dict_tick[code][0]
                    bid_volumns = self.dict_tick[code][1]
                    ask_volumns = self.dict_tick[code][2]
                except KeyError:
                    pret = None
                    bid_volumns = 0
                    ask_volumns = 0
                if v > 0:
                    self.dict_tick[code] = [t, bid_volumns + abs(v), ask_volumns]
                else:
                    self.dict_tick[code] = [t, bid_volumns, ask_volumns + abs(v)]
                if t != pret:
                    bids = self.dict_tick[code][1]
                    asks = self.dict_tick[code][2]
                    self.dict_tick[code] = [t, 0, 0]
                    try:
                        h = abs(int(self.GetCommRealData(code, 17)))
                        low = abs(int(self.GetCommRealData(code, 18)))
                        per = float(self.GetCommRealData(code, 12))
                        dm = int(self.GetCommRealData(code, 14))
                        ch = float(self.GetCommRealData(code, 228))
                        vp = abs(float(self.GetCommRealData(code, 30)))
                        name = self.GetMasterCodeName(code)
                    except Exception as e:
                        self.windowQ.put([1, f'OnReceiveRealData 주식체결 {e}'])
                    else:
                        self.UpdateTickData(code, name, c, o, h, low, per, dm, ch, vp, bids, asks, t, now())
        elif realtype == '주식호가잔량':
            try:
                s2hg = abs(int(self.GetCommRealData(code, 42)))
                s1hg = abs(int(self.GetCommRealData(code, 41)))
                b1hg = abs(int(self.GetCommRealData(code, 51)))
                b2hg = abs(int(self.GetCommRealData(code, 52)))
                s2jr = int(self.GetCommRealData(code, 62))
                s1jr = int(self.GetCommRealData(code, 61))
                b1jr = int(self.GetCommRealData(code, 71))
                b2jr = int(self.GetCommRealData(code, 72))
            except Exception as e:
                self.windowQ.put([1, f'OnReceiveRealData 주식호가잔량 {e}'])
            else:
                self.dict_hoga[code] = [s2hg, s1hg, b1hg, b2hg, s2jr, s1jr, b1jr, b2jr]

    def InsertViPriceDown5(self, code, o):
        vid5 = self.GetVIPriceDown5(code, o)
        self.dict_vipr[code] = [True, timedelta_sec(-180), vid5]

    def GetVIPriceDown5(self, code, std_price):
        vi = std_price * 1.1
        x = self.GetHogaunit(code, vi)
        if vi % x != 0:
            vi = vi + (x - vi % x)
        return int(vi - x * 5)

    def GetHogaunit(self, code, price):
        if price < 1000:
            x = 1
        elif 1000 <= price < 5000:
            x = 5
        elif 5000 <= price < 10000:
            x = 10
        elif 10000 <= price < 50000:
            x = 50
        elif code in self.list_kosd:
            x = 100
        elif 50000 <= price < 100000:
            x = 100
        elif 100000 <= price < 500000:
            x = 500
        else:
            x = 1000
        return x

    def UpdateViPriceDown5(self, code, key):
        if type(key) == str:
            if code in self.dict_vipr.keys():
                self.dict_vipr[code][0] = False
                self.dict_vipr[code][1] = timedelta_sec(5)
            else:
                self.dict_vipr[code] = [False, timedelta_sec(5), 0]
            self.windowQ.put([1, f'변동성 완화 장치 발동 - [{code}] {key}'])
        elif type(key) == int:
            vid5 = self.GetVIPriceDown5(code, key)
            self.dict_vipr[code] = [True, timedelta_sec(5), vid5]

    def UpdateTickData(self, code, name, c, o, h, low, per, dm, ch, vp, bids, asks, t, receivetime):
        dt = self.str_tday + t[:4]
        if code not in self.dict_cdjm.keys():
            columns = ['1분누적거래대금', '1분전당일거래대금']
            self.dict_cdjm[code] = pd.DataFrame([[0, dm]], columns=columns, index=[dt])
        elif dt == self.dict_cdjm[code].index[-1]:
            predm = self.dict_cdjm[code]['1분전당일거래대금'][-1]
            self.dict_cdjm[code].at[dt] = dm - predm, predm
        else:
            if len(self.dict_cdjm[code]) >= 15:
                if per > 0:
                    self.df_mc.at[code] = self.dict_cdjm[code]['1분누적거래대금'].sum()
                self.dict_cdjm[code].drop(index=self.dict_cdjm[code].index[0], inplace=True)
            predm = self.dict_cdjm[code]['1분전당일거래대금'][-1] + self.dict_cdjm[code]['1분누적거래대금'][-1]
            self.dict_cdjm[code].at[dt] = dm - predm, predm

        if code in self.dict_gsjm.keys():
            injango = code in self.list_jang
            vitimedown = now() < timedelta_sec(180, self.dict_vipr[code][1])
            vid5priceup = c >= self.dict_vipr[code][2]
            self.stgQ.put([code, name, c, o, h, low, per, ch, dm, t, injango, vitimedown, vid5priceup, receivetime])

        vitime = strf_time('%Y%m%d%H%M%S', self.dict_vipr[code][1])
        vid5 = self.dict_vipr[code][2]
        try:
            s2hg, s1hg, b1hg, b2hg, s2jr, s1jr, b1jr, b2jr = self.dict_hoga[code]
        except KeyError:
            s2hg, s1hg, b1hg, b2hg, s2jr, s1jr, b1jr, b2jr = 0, 0, 0, 0, 0, 0, 0, 0
        data = [code, c, o, h, low, per, dm, ch, vp, bids, asks, vitime, vid5,
                s2hg, s1hg, b1hg, b2hg, s2jr, s1jr, b1jr, b2jr, t, receivetime]
        if code in self.list_code1:
            self.tick1Q.put(data)
        elif code in self.list_code2:
            self.tick2Q.put(data)
        elif code in self.list_code3:
            self.tick3Q.put(data)
        elif code in self.list_code4:
            self.tick4Q.put(data)

    def OnReceiveTrData(self, screen, rqname, trcode, record, nnext):
        if screen == '' and record == '':
            return
        items = None
        self.dict_bool['TR다음'] = True if nnext == '2' else False
        for output in self.dict_item['output']:
            record = list(output.keys())[0]
            items = list(output.values())[0]
            if record == self.str_tname:
                break
        rows = self.ocx.dynamicCall('GetRepeatCnt(QString, QString)', trcode, rqname)
        if rows == 0:
            rows = 1
        df2 = []
        for row in range(rows):
            row_data = []
            for item in items:
                data = self.ocx.dynamicCall('GetCommData(QString, QString, int, QString)', trcode, rqname, row, item)
                row_data.append(data.strip())
            df2.append(row_data)
        df = pd.DataFrame(data=df2, columns=items)
        self.df_tr = df
        self.dict_bool['TR수신'] = True

    def Block_Request(self, *args, **kwargs):
        trcode = args[0].lower()
        liness = readEnc(trcode)
        self.dict_item = parseDat(trcode, liness)
        self.str_tname = kwargs['output']
        nnext = kwargs['next']
        for i in kwargs:
            if i.lower() != 'output' and i.lower() != 'next':
                self.ocx.dynamicCall('SetInputValue(QString, QString)', i, kwargs[i])
        self.dict_bool['TR수신'] = False
        self.dict_bool['TR다음'] = False
        self.ocx.dynamicCall('CommRqData(QString, QString, int, QString)', self.str_tname, trcode, nnext, sn_brrq)
        sleeptime = timedelta_sec(0.25)
        while not self.dict_bool['TR수신'] or now() < sleeptime:
            pythoncom.PumpWaitingMessages()
        return self.df_tr

    def SendCondition(self, screen, cond_name, cond_index, search):
        self.dict_bool['CR수신'] = False
        self.ocx.dynamicCall('SendCondition(QString, QString, int, int)', screen, cond_name, cond_index, search)
        while not self.dict_bool['CR수신']:
            pythoncom.PumpWaitingMessages()
        return self.list_trcd

    def GetMasterCodeName(self, code):
        return self.ocx.dynamicCall('GetMasterCodeName(QString)', code)

    def GetCodeListByMarket(self, market):
        data = self.ocx.dynamicCall('GetCodeListByMarket(QString)', market)
        tokens = data.split(';')[:-1]
        return tokens

    def GetCommRealData(self, code, fid):
        return self.ocx.dynamicCall('GetCommRealData(QString, int)', code, fid)