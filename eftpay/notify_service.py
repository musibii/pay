@tornado.gen.coroutine
def notify(self, params):
    """
    回调通知
    :param params:
    :return:
    """
    # 交易成功
    self.logger.info('eft notify: %s' % params)
    notify_params = params['request_body']
    cache_key = self.cache_key_predix.ORDER_NOTIFY + params['request_body']['out_trade_no']
    self.logger.info('cache_key: %s' % cache_key)
    final_pay = yield self.redis.hgetall(cache_key)

    if not final_pay:
        raise self._gre('PAY_PARAMS_NOT_ERROR')
    self.logger.info('eftpay notify: %s', params)

    # 验签
    verify_result = self.verify_sign(params['request_body'], final_pay)
    if not verify_result:
        self.logger.info('eftpay notify check sign failed....')
        raise self._gre('PAY_EFTPAY_SIGN_ERROR')

    # if params['trade_status'] == self.trade_success:
        # 根据母单号查到母单信息
    order = yield self.do_service(
        'order.service',
        'query_order_list',
        {
            'parent_order_id': params['request_body']['out_trade_no']
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
                    'parent_order_id': params['request_body']['out_trade_no'],
                    'pay_type': self.constants.PAY_TYPE_EFTPAY
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
                    'parent_order_id': params['request_body']['out_trade_no'],
                    'pay_type': self.constants.PAY_TYPE_EFTPAY,
                    'pay_amount': float(params['request_body']['total_fee']) * 100,
                    'trade_no': params['request_body']['transaction_id'],
                    'pay_channel': params['request_body']['paytype'],
                    'rate': params['request_body'].get('rate', 1)
                },
                'order_data': {
                    'parent_order_id': params['request_body']['out_trade_no'],
                    'status': self.constants.ORDER_PAY_SUCCESS
                }
            }

            # 3. 调用创建支付记录接口
            pay_result = yield self.do_service('order.payment.service', 'pay_success', data)

            if pay_result['code'] == 0:
                yield self.redis.delete(cache_key)

            # 4. 落地 eft_order_no、init_response等数据
            update_params = {
                'parent_order_id': params['request_body']['out_trade_no'],
                'init_response': self.json.dumps(notify_params),
                'eft_order_no': params['request_body']['eftpay_trade_no'],
                'trade_no': params['request_body']['transaction_id'],
                'pay_success_time': params['request_body']['gmt_payment']
            }
            result = yield self.do_service('order.log.service', 'update_order_pay_log', update_params)

            if result['code'] != 0:
                self.logger.info('update_order_pay_log: %s' % update_params)
            return_params = {
                'return_code': 'success',
                'time': self.time.strftime('%Y%m%d%H%M%S', self.time.localtime(self.time.time()))
            }
            raise self._grs(self._create_params(return_params, final_pay))

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
    final_str = final_pay['private_key'] + params_str
    sign = self.hashlib.sha256(final_str.encode('utf-8'))
    # sign.update(self.private_key.encode('utf-8'))
    return original_sign == sign.hexdigest()

def _create_sign(self, params, final_pay):
    """
    生成支付签名
    :param params:
    :return:
    """
    sorted_keys = sorted(params.keys())
    params_list = [str(k) + '=' + str(params[k]) for k in sorted_keys if params[k] != '']
    params_str = '&'.join(params_list)
    final_str = final_pay['private_key'] + params_str
    sign = self.hashlib.sha256(final_str.encode('utf-8'))
    # sign.update(self.private_key.encode('utf-8'))
    return sign.hexdigest()

def _create_params(self, params, final_pay):
    """
    将 sign 合并到上传参数里面
    :param params:
    :return:
    """
    params['sign'] = self._create_sign(params, final_pay)
    return params
