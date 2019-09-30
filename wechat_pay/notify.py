@tornado.gen.coroutine
def get(self):
    params = {
        'xml': self.request.body
    }
    self.logger.info(params['xml'])

    res = yield self.do_service('plugins.jala.pay.notify_service', 'notify', params=params)
    if res['code'] == 0:
        self.write('<xml><return_code><![CDATA[SUCCESS]]>'
                   '</return_code><return_msg><![CDATA[OK]]></return_msg></xml>')
    else:
        self.write('notify failed')

@tornado.gen.coroutine
def post(self):
    params = {
        'xml': self.request.body
    }
    self.logger.info(params['xml'])

    res = yield self.do_service('plugins.jala.pay.notify_service', 'notify', params=params)
    if res['code'] == 0:
        self.write('<xml><return_code><![CDATA[SUCCESS]]>'
                   '</return_code><return_msg><![CDATA[OK]]></return_msg></xml>')
    else:
        self.write('notify failed')
