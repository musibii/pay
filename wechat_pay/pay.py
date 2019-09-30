import tornado.gen
import re

import xmltodict
from base.service import ServiceBase
from source.properties import Properties


class Service(ServiceBase):
    """
    service
    """
    jala_wechatpay = Properties('jala_wechatpay')
    base = jala_wechatpay.get('host', 'BASE')
    notify_url = jala_wechatpay.get('host', 'NOTIFY_URL')
    refund_url = jala_wechatpay.get('host', 'REFUND_URL')
    request_url = jala_wechatpay.get('host', 'REQUEST_URL')

    def __init__(self):
        """
        对象初始化方法
        添加你需要使用的model
        格式 项目model文件夹下的文件名或者 包名1.包名2.文件名 (无.py后缀)
        """
        # self.model = self.import_model('')

    @tornado.gen.coroutine
    def create_pay(self, params):
        """
         创建微信支付获取拉起支付数据
        :param params: 
        :return: 
        """
        check_params = [
            'out_trade_no',
            'total_fee',
            'spbill_create_ip',
            'body',
            'openid',
            'shop_id'
        ]
        if self.common_utils.is_empty(check_params, params):
            raise self._gre('PARAMS_NOT_EXIST')

        final_pay = None
        if not params['self_pay']:
            pay_result = yield self.do_service('cfg.payment.service', 'query_payments_list', params)
            if pay_result['code'] != 0:
                raise self._gr(pay_result)

            for pay_item in pay_result['data']:
                if int(pay_item['pay_type']) == self.constants.PAY_TYPE_WECHAT:
                    final_pay = pay_item
                    break

            if not isinstance(final_pay, dict):
                raise self._gre('PAY_PAY_PARAMS_NOT_EXIST')
        else:
            final_pay = params['self_pay']

        cache_key = self.cache_key_predix.ORDER_NOTIFY + params['out_trade_no']
        yield self.redis.hmset(cache_key, final_pay, int(params['order_expire_time']) * 60)

        # 重复支付时从 redis 里面获取 payPackage，1. 判断订单支付状态；2. 获取 payPackage 返回给前端
        order_result = yield self.do_service(
            'order.service',
            'query_sub_order_list',
            {
                'parent_order_id': params['out_trade_no'],
                'shop_id': params['shop_id']
            })

        # 如果查询子订单出错或者子订单状态不为 1 则说明该订单已支付
        if order_result['code'] != 0 or order_result['data'][0]['status'] != 1:
            raise self._gr(order_result)

        order_pay_cache_key = self.cache_key_predix.ORDER_PAY + params['out_trade_no']
        pay_package = yield self.redis.hgetall(order_pay_cache_key)

        if pay_package:
            raise self._grs(pay_package)

        # 组装请求参数
        request_params = {
            'appid': final_pay['app_id'],
            'openid': params['openid'],
            'mch_id': final_pay['mch_id'],
            'body': params['body'],
            'nonce_str': self.create_uuid(),
            'out_trade_no': params['out_trade_no'],
            'total_fee': params['total_fee'],
            'spbill_create_ip': params['spbill_create_ip'],
            'notify_url': self.base + self.notify_url,
            'trade_type': 'JSAPI',
            'time_start': re.sub(r'\s|:|-', '', str(params['order_create_time'])),
            'time_expire': re.sub(r'\s|:|-', '', self.date_utils.add_minute(str(params['order_create_time']),
                                                                            minutes=int(params['order_expire_time'])))
        }

        self.logger.info('jala_wechatpay_params: %s' % request_params)

        post_params = self._create_params(request_params, final_pay)

        request_xml = ['<xml>']
        for (k, v) in post_params.items():
            request_xml.append('<' + k + '>' + str(v) + '</' + k + '>')
        request_xml.append('</xml>')
        self.logger.info(request_xml)

        res = yield self.httputils.post(self.request_url, params=''.join(request_xml))
        self.logger.info(res)

        try:
            xml_data = xmltodict.parse(res)
        except Exception as e:
            self.logger.exception(e)
            raise self._gre('PAY_NOTIFY_XML_ERROR')

        xml_data = xml_data['xml']

        if xml_data['return_code'] == 'SUCCESS' and xml_data['result_code'] == 'SUCCESS':

            result = self._build_h5_response(xml_data, final_pay)

            # 预支付数据获取成功存进 redis 中
            # 拉起第二次支付把预支付参数存进 redis
            # order_pay_cache_key = self.cache_key_predix.ORDER_PAY + params['out_trade_no']
            yield self.redis.hmset(order_pay_cache_key, result, int(params['order_expire_time']) * 61)
            raise self._grs(result)

        else:
            raise self._gre('PAY_PREPAY_ID_ERROR')

    def _create_params(self, params, final_pay):
        """
        组装请求参数
        :param params:
        :return:
        """
        params['sign'] = self._create_sign(params, final_pay)
        return params

    def _create_sign(self, params, final_pay):
        """
        生成支付签名
        :param params:
        :return:
        """
        sorted_keys = sorted(params.keys())
        params_list = [str(k) + '=' + str(params[k]) for k in sorted_keys if params[k] != '']
        params_str = '&'.join(params_list)
        final_str = params_str + '&key=' + final_pay['mch_api_key']
        sign = self.hashlib.md5(final_str.encode('utf-8'))
        # sign.update(self.private_key.encode('utf-8'))
        return sign.hexdigest().upper()

    def _build_h5_response(self, xml_data, pay_params):
        """
        构建h5调起微信支付返回数据对象
        :param xml_data:
        :param pay_params:
        :return:
        """
        time_stamp = str(self.time.time()).split('.')[0]
        pay_sign_list = [
            'appId=' + pay_params['app_id'],
            'nonceStr=' + xml_data['nonce_str'],
            'package=prepay_id=' + xml_data['prepay_id'],
            'signType=MD5',
            'timeStamp=' + time_stamp,
            'key=' + pay_params['mch_api_key']
        ]
        self.logger.info('&'.join(pay_sign_list))
        pay_sign = self.md5('&'.join(pay_sign_list))
        result = {
            'appId': pay_params['app_id'],
            'nonceStr': xml_data['nonce_str'],
            'package': 'prepay_id=' + xml_data['prepay_id'],
            'signType': 'MD5',
            'timeStamp': time_stamp,
            'paySign': pay_sign
        }

        return result

    @tornado.gen.coroutine
    def refund(self, params):
        """
        微信退款
        :param params:
        :return:
        """
