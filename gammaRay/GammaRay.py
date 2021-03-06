#DO NOT CHANGE this file (setupApps depends on them)
import boto3,json,logging,os,sys,importlib,zipfile,traceback
import time,uuid
from fleece.xray import (monkey_patch_botocore_for_xray,
                         monkey_patch_requests_for_xray,
                         trace_xray_subsegment)

monkey_patch_botocore_for_xray()
monkey_patch_requests_for_xray()
sessionID = str(uuid.uuid4())

def callIt(event,context):
    #DO NOT CHANGE the following two lines (setupApps depends on them)
    #create a new file if changes are necessary
    import GammaRayTemplate
    return GammaRayTemplate.handler(event,context)

def handleRequest(event, context):
    logger = logging.getLogger()
    entry = time.time() * 1000
    reqID = 'unknown'
    arn = 'unknown'
    if context:
        reqID = context.aws_request_id
        arn = context.invoked_function_arn
    payload = 'pl:{}:{}'.format(reqID,arn)
    if 'eventSource' in event:
        payload += ':es:{}'.format(event['eventSource'])
    if 'Records' in event:
        recs = event['Records']
        parent_obj = recs[0]
        if 'dynamodb' in parent_obj: 
            obj = parent_obj['dynamodb']
            payload += ':es:ddb'
            subobj = obj['Keys']
            payload += ':keys'
            for key in subobj:
                payload += ':{}'.format(key)
            payload += ':op:{}'.format(parent_obj['eventName'])
        elif 'Sns' in parent_obj: 
            obj = parent_obj['Sns']
            payload += ':es:sns'
            payload += ':sub:{}'.format(obj['Subject'])
            payload += ':op:{}'.format(obj['TopicArn'])
        elif 's3' in parent_obj: 
            payload += ':es:s3'
            obj = parent_obj['s3']
            subobj = obj['bucket']
            payload += ':bkt:{}'.format(subobj['name'])
            subobj = obj['object']
            payload += ':key:{}'.format(subobj['key'])
            payload += ':op:{}'.format(parent_obj['eventName'])

    dynamodb = boto3.resource('dynamodb', region_name='ZZZZ')
    table = dynamodb.Table('QQQQ')
    unique_str = str(uuid.uuid4())[:8]
    entstr = 'entry{}'.format(unique_str)
    tsint = int(round(time.time() * 1000)) #msecs in UTC
    reqID += ':{}'.format(entstr)
    table.put_item( Item={
        'reqID': reqID,
        'ts': tsint,
        'payload': payload
        }
    )

    os.environ['spotReqID'] = reqID
    os.environ['myArn'] = arn
    os.environ['gammaTable'] = 'QQQQ'
    os.environ['gammaRegion'] = 'ZZZZ'
    errorstr = "GammaWrapPython"
    logger.warn('GammaWrapPython::reqID:{}'.format(reqID))
    respObj = {}
    returnObj = {}
    status = '200'
    delta = 0
    wrappedentry = time.time() * 1000
    ERR = False
    try: 
        if 'nowrap' in event:
            respObj = None
        else:
            respObj = callIt(event,context)
        if not respObj:
            respObj = {}
            respObj['GammaWrapMessage'] = 'NoResponseReturned'
        if 'statusCode' in respObj:
            status = respObj['statusCode']
            if status != '200':
                ERR = True
                if 'exception' in respObj:
                    errorstr += ':{}:status:{}'.format(respObj['exception'],errcode)
                else:
                    errorstr += ':error_unknown:status:{}'.format(errcode)
    except Exception as e:
        _, _, exc_traceback = sys.exc_info()
        msg = repr(traceback.format_tb(exc_traceback))
        errorstr += ':GammaWrap_exception:{}:{}:status:400'.format(e,msg)
        ERR = True
    finally: 
        if errorstr != 'GammaWrapPython':
            print('GammaWrapPy caught error: {}'.format(errorstr))
        delta = (time.time() * 1000) - wrappedentry

    if not respObj: 
        respObj = {}
    if ERR:
        status = '400'
        respObj['GammaWrapError']=errorstr
    returnObj['statusCode'] = status
    returnObj['body'] = respObj
    selfdelta = (time.time() * 1000) - entry
    logger.warn('GammaWrapPython::handleRequest:TIMER:CALL:{}:WRAPPEDCALL:{}:status:{}:response:{}'.format(selfdelta,delta,status,respObj))
    return returnObj
    
