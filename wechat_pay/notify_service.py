class Service(ServiceBase):
    """
    service
    """
    model = None

    def __init__(self):
        """
        对象初始化方法
        添加你需要使用的model
        格式 项目model文件夹下的文件名或者 包名1.包名2.文件名 (无.py后缀)
        """

    @tornado.gen.coroutine
    def notify(self, params):
        """
        微信支付回调通知
        :param params: 
        :return: 
        """
        try:
            xml_data = xmltodict.parse(params['xml'])
        except Exception as e:
            self.logger.exception(e)
            raise self._gre('PAY_NOTIFY_XML_ERROR')

        xml_data = xml_data['xml']
        self.logger.info('wechatpay notify: %s' % xml_data)
        cache_key = self.cache_key_predix.ORDER_NOTIFY + xml_data['out_trade_no']
        order_pay_cache_key = self.cache_key_predix.ORDER_PAY + xml_data['out_trade_no']
        self.logger.info('cache_key: %s' % cache_key)
        final_pay = yield self.redis.hgetall(cache_key)

        if not final_pay:
            raise self._gre('PAY_PARAMS_NOT_ERROR')
        self.logger.info('wechatpay notify: %s', params)

        # 验签
        verify_result = self.verify_sign(xml_data, final_pay)
        if not verify_result:
            self.logger.info('wechat pay notify check sign failed....')
            raise self._gre('SIGN_VERIFY_FAILED')

        if xml_data['return_code'] == 'SUCCESS':
            order = yield self.do_service(
                'order.service',
                'query_order_list',
                {
                    'parent_order_id': xml_data['out_trade_no']
                })

            if order['code'] != 0:
                raise self._gr(order)

            else:
                order_data = order['data'][0]
                if order_data['status'] != 1:
                    raise self._gre('ORDER_STATUS_ERROR')

                # 查询订单支付信息，防止重复通知
                pay_result = yield self.do_service(
                    'order.payment.service',
                    'query_payment_by_parent',
                    {
                        'parent_order_id': xml_data['out_trade_no'],
                        'pay_type': self.constants.PAY_TYPE_WECHAT
                    }
                )
                if pay_result['code'] == 0:
                    raise self._gre('PAY_REPEAT_NOTIFY')

                # 修改订单支付状态为已支付
                data = {
                    'payment': {
                        'pay_order_id': self.create_uuid(),
                        'shop_id': order_data['shop_id'],
                        'order_id': '',
                        'parent_order_id': xml_data['out_trade_no'],
                        'pay_type': self.constants.PAY_TYPE_WECHAT,
                        'pay_amount': xml_data['total_fee'],
                        'trade_no': xml_data['transaction_id'],
                        'pay_channel': 'wechat'
                    },
                    'order_data': {
                        'parent_order_id': xml_data['out_trade_no'],
                        'status': self.constants.ORDER_PAY_SUCCESS
                    }
                }

                # 3. 调用创建支付记录接口
                pay_result = yield self.do_service('order.payment.service', 'pay_success', data)

                if pay_result['code'] == 0:
                    yield self.redis.delete(cache_key)
                    yield self.redis.delete(order_pay_cache_key)

                    raise self._grs()

    def verify_sign(self, params, final_pay):
        """
        解析返回的签名数据
        :param params:
        :param final_pay
        :return:
        """
        original_sign = params.pop('sign')
        sorted_keys = sorted(params.keys())
        params_list = [str(k) + '=' + str(params[k]) for k in sorted_keys if params[k] != '']
        params_str = '&'.join(params_list)
        final_str = params_str + '&key=' + final_pay['mch_api_key']
        sign = self.hashlib.md5(final_str.encode('utf-8'))
        # sign.update(self.private_key.encode('utf-8'))
        return original_sign == sign.hexdigest().upper()

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
