class Service(ServiceBase):
    eftpay_properties = Properties('eftpay')
    api_host = eftpay_properties.get('api', 'URL')
    user_confirm_key = eftpay_properties.get('secret', 'USER_CONFIRM_KEY')
    private_key = eftpay_properties.get('secret', 'PRIVATE_KEY')
    service = eftpay_properties.get('pay', 'SERVICE')
    pay_type = eftpay_properties.get('pay', 'PAY_TYPE')
    payment_type = eftpay_properties.get('pay', 'PAYMENT_TYPE')
    scene_type = eftpay_properties.get('wmp', 'SCENE_TYPE')
    fee_type = eftpay_properties.get('pay', 'FEE_TYPE')
    notify_url = eftpay_properties.get('api', 'NOTIFY_URL')
    success_status = eftpay_properties.get('pay_status', 'SUCCESS_STATUS')
    refund_service = eftpay_properties.get('pay', 'REFUND_SERVICE')
    base_url = eftpay_properties.get('api', 'HOST')
    query_url = eftpay_properties.get('api', 'QUERY_URL')

    @tornado.gen.coroutine
    def create_pay(self, params):
        """
        创建 eftpay 支付
        :param params:
        :return:
        """
        # 检查参数
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
            pay_result = yield self.do_service('channel.cfg.payment.service', 'query_payments_list', params)
            if pay_result['code'] != 0:
                raise self._gr(pay_result)

            for pay_item in pay_result['data']:
                if int(pay_item['pay_type']) == self.constants.PAY_TYPE_EFTPAY:
                    final_pay = pay_item
                    break

            if not isinstance(final_pay, dict):
                raise self._gre('PAY_PAY_PARAMS_NOT_EXIST')
        else:
            final_pay = params['self_pay']
        self.logger.info('final_pay: %s' % final_pay)
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

        request_params = {
            'service': self.service,
            'user_confirm_key': self.user_confirm_key,
            'paytype': self.pay_type,
            'sub_openid': params['openid'],
            'transaction_amount': str(float(params['total_fee']) / 100),
            'out_trade_no': params['out_trade_no'],
            # 'subject': params['body'],
            'time': self.time.strftime('%Y%m%d%H%M%S', self.time.localtime(self.time.time())),
            'payment_type': self.payment_type,
            'scene_type': self.scene_type,
            'fee_type': self.fee_type,
            'notify_url': self.base_url + self.notify_url
        }

        self.logger.info('eftpay_params: %s' % request_params)

        post_params = self._create_params(request_params)
        res = yield self.httputils.post(self.api_host,
                                        params=self.json.dumps(post_params),
                                        is_json=True)
        if res['return_status'] != self.success_status:
            raise self._gr(res)

        # 拉起第二次支付把预支付参数存进 redis
        order_pay_cache_key = self.cache_key_predix.ORDER_PAY + params['out_trade_no']
        yield self.redis.hmset(order_pay_cache_key, res['payPackage'], int(params['order_expire_time'] * 61))

        # 把parent_order_id、pay_channel、pay_type、init_request 落地
        need_params = {
            'parent_order_id': params['out_trade_no'],
            'pay_channel': 'eftpay',
            'pay_type': self.pay_type,
            'init_request': self.json.dumps(request_params),
        }

        result = yield self.do_service('order.log.service', 'save_order_pay_log', need_params)
        if result['code'] != 0:
            self.logger.info('pay_log request_params: %s' % need_params)

        raise self._grs(res['payPackage'])

    def _create_sign(self, params):
        """
        生成支付签名
        :param params:
        :return:
        """
        sorted_keys = sorted(params.keys())
        params_list = [str(k) + '=' + str(params[k]) for k in sorted_keys if params[k] != '']
        params_str = '&'.join(params_list)
        final_str = self.private_key + params_str
        sign = self.hashlib.sha256(final_str.encode('utf-8'))
        # sign.update(self.private_key.encode('utf-8'))
        return sign.hexdigest()

    def _create_params(self, params):
        """
        将 sign 合并到上传参数里面
        :param params:
        :return:
        """
        params['sign'] = self._create_sign(params)
        return params

    @tornado.gen.coroutine
    def refund(self, params):
        """
        创建 eftpay 退款
        :param params:
        :return:
        """
        # 检查参数
        check_params = [
            'out_trade_no',
            'shop_id',
            'refund_amount',
            'trade_no',
            'order_money',
        ]
        if self.common_utils.is_empty(check_params, params):
            raise self._gre('PARAMS_NOT_EXIST')

        final_pay = None
        if not params['self_pay']:
            pay_result = yield self.do_service('channel.cfg.payment.service', 'query_payments_list', params)
            if pay_result['code'] != 0:
                raise self._gr(pay_result)

            for pay_item in pay_result['data']:
                if int(pay_item['pay_type']) == self.constants.PAY_TYPE_EFTPAY:
                    final_pay = pay_item
                    break

            if not isinstance(final_pay, dict):
                raise self._gre('PAY_PAY_PARAMS_NOT_EXIST')
        else:
            final_pay = params['self_pay']

        # 根据母单号查询母单总金额
        parent_result = yield self.do_service(
            'order.parent.service',
            'single_query',
            {
                'parent_order_id': params['out_trade_no'],
                'shop_id': params['shop_id']
            })

        if parent_result['code'] != 0:
            raise self._gr(parent_result)

        refund_params = {
            'service': self.refund_service,
            'user_confirm_key': self.user_confirm_key,
            'paytype': self.pay_type,
            'transaction_amount': str(float(params['refund_amount']) / 100),
            'out_trade_no': params['out_trade_no'],
            'time': self.time.strftime('%Y%m%d%H%M%S', self.time.localtime(self.time.time())),
            'refund_no': params['batch_no'],
            'total_fee': str(float(parent_result['data']['pay_amount']) / 100),
            'payment_type': self.payment_type,
        }

        post_params = self._create_params(refund_params)
        res = yield self.httputils.post(self.api_host,
                                        params=self.json.dumps(post_params),
                                        is_json=True)
        if res['return_status'] != self.success_status:
            raise self._gr(res)

        raise self._grs(res)

