#DO NOT CHANGE this file (setupApps depends on them)
import boto3,json,logging,os,sys,importlib,zipfile,traceback
import time,uuid
sessionID = str(uuid.uuid4())

def callIt(event,context):
    #DO NOT CHANGE the following two lines (setupApps depends on them)
    #create a new file if changes are necessary
    import SpotTemplate
    return SpotTemplate.handler(event,context)

def handleRequest(event, context):
    logger = logging.getLogger()
    entry = time.time() * 1000

    ''' Download the zip file from s3, unzip it into libdir, 
        put it in the path and reload botocore.client to get the changes.
    '''
    libdir = '/tmp/spotlibs'
    botoname = '{}/botocore'.format(libdir)
    #first check if here (container reuse), if not then load it, else use it
    if not os.path.exists(botoname): 
        bkt = 'XXXX' #do not change this text as it is replaced
        fname = 'YYYY' #do not change this text as it is replaced
        tmpfname = '/tmp/{}'.format(fname)
        s3 = boto3.resource('s3')
        try:
            s3.Bucket(bkt).download_file(fname, tmpfname)
        except Exception as e:
            print('Error, s3 GET exception (unable to download libfile {}/{} to tmp):\n{}'.format(bkt,fname,e))
        with zipfile.ZipFile(tmpfname, 'r') as z:
            z.extractall(path=libdir)

    sys.path.insert(0, libdir)
    import botocore
    importlib.invalidate_caches()
    importlib.import_module('botocore')
    importlib.reload(botocore)
    importlib.reload(botocore.client)

    reqID = 'unknown'
    arn = 'unknown'
    if context:
        reqID = context.aws_request_id
        arn = context.invoked_function_arn
    os.environ['spotReqID'] = reqID
    os.environ['myArn'] = arn
    ERR = False
    errorstr = "SpotWrapPython"
    unique_str = str(uuid.uuid4())[:8]
    entstr = 'entry{}'.format(unique_str)
    exstr = 'exit{}'.format(unique_str)
    makeRecord(context,event,0,errorstr,entstr)
    respObj = {}
    returnObj = {}
    status = '200'
    delta = 0
    wrappedentry = time.time() * 1000
    try: 
        respObj = callIt(event,context)
        if not respObj:
            respObj = {}
            respObj['SpotWrapMessage'] = 'NoResponseReturned'
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
        errorstr += ':SpotWrap_exception:{}:{}:status:400'.format(e,msg)
        ERR = True
    finally: 
        if errorstr != 'SpotWrapPython':
            print('SpotWrapPy caught error: {}'.format(errorstr))
        delta = (time.time() * 1000) - wrappedentry
        duration = int(round(delta))
        makeRecord(context,None,duration,errorstr,exstr) #end event (event arg = null)

    if not respObj: 
        respObj = {}
    if ERR:
        status = '400'
        respObj['SpotWrapError']=errorstr
    returnObj['statusCode'] = status
    returnObj['body'] = respObj
    selfdelta = (time.time() * 1000) - entry
    logger.info('SpotWrapPython::handleRequest:TIMER:CALL:{}:WRAPPEDCALL:{}:status:{}:response:{}'.format(selfdelta,delta,status,respObj))
    return returnObj
    
def makeRecord(context,event,duration,errorstr,prefix): 
    logger = logging.getLogger()
    #setup record defaults
    eventSource = "unknown"
    eventOp = "unknown"
    caller = "unknown"
    sourceIP = "unknown"
    msg = "unset" #random info
    requestID = sessionID #reqID of this aws lambda function set random as default
    functionName = "unset" #this aws lambda function name
    myarn = "unset"
    region = "unset"
    accountID = "unset"
    APIGW = 1
    DYNDB = 2
    S3 = 3
    SNS = 4
    INVCLI = 5
    UNKNOWN = 0
    flag = UNKNOWN

    if context:
        myarn = context.invoked_function_arn
        arns = myarn.split(":")
        accountID = arns[4]
        region = arns[3]
        requestID = context.aws_request_id
        functionName = context.function_name

    if event:
        if 'requestId' in event:
            caller = event['requestId']
        if 'eventSource' in event:
            eventSource = event['eventSource']

        #figure out source and process appropriately
        if 'requestContext' in event:
            #API Gateway
            flag = APIGW
            req = event['requestContext']
            eventSource = 'aws:APIGateway:{}'.format(req['apiId'])
            msg = req['resourceId']
            acct = req['accountId']
            if accountID == 'unset':
                accountID = acct
            elif acct != accountID:
                accountID +=':{}'.format(acct)
            caller = req['requestId']
            eventOp = req['path']
            tmpObj = req['identity']
            sourceIP = tmpObj['sourceIp']
            if 'queryStringParameters' in event:
                req = event['queryStringParameters']
                if req: 
                    if 'msg' in req:
                        msg += ':{}'.format(req['msg'])
                else: #req is null, try body
                    req = event['body']
                    if req:
                        msg += ':curl:{}'.format(req)
  
        elif 'Records' in event:
            #S3 or DynamoDB or SNS or unknown
            recs = event['Records']
            obj = recs[0]
            if 'eventSource' in obj:
                eventSource = obj['eventSource']
            if 'EventSource' in obj: #aws:sns
                eventSource = obj['EventSource']
            if eventSource.startswith('aws:sns'):
                flag = SNS
                if 'EventSubscriptionArn' in obj:
                    eventSource = obj['EventSubscriptionArn']
                else: 
                    eventSource = 'unknown_aws:sns'
                if 'Sns' in obj:
                    snsObj = obj['Sns']
                    if 'Type' in snsObj:
                        eventOp = snsObj['Type']
                    if 'MessageId' in snsObj:
                        caller = snsObj['MessageId']
                    if 'Subject' in snsObj:
                        msg = snsObj['Subject']
                    if 'Message' in snsObj:
                        msg += ':{}'.format(snsObj['Message'])
		
            elif eventSource.startswith('aws:s3'):
                flag = S3
                s3obj = None
                s3bkt = None
                s3bktobj = None
                if 's3' in obj:
                    s3obj = obj['s3']
                if 'responseElements' in obj:
                    caller = obj['responseElements']['x-amz-request-id']
                if 'requestParameters' in obj:
                    sourceIP = obj['requestParameters']['sourceIPAddress']
                if 'userIdentity' in obj:
                    accountID = obj['userIdentity']['principalId']
                if 'awsRegion' in obj:
                    reg = obj['awsRegion']
                    if region != reg:
                        region +=':{}'.format(reg)
                if 'eventName' in obj:
                    eventOp = obj['eventName']
                if s3obj:
                    if 'bucket' in s3obj:
                        s3bkt = s3obj['bucket']
                        if 'arn' in s3bkt:
                            eventSource = '{}:{}'.format(s3bkt['arn'],eventOp)
                    if 'object' in s3obj:
                        s3bktobj = s3obj['object']
                if s3bkt and s3bktobj:
                    size = 0
                    if 'size' in s3bktobj:
                        size = s3bktobj['size']
                    msg = '{}:{}:{}:{}'.format(s3bkt['name'],s3bktobj['key'],size,obj['eventTime'])
                    caller += ':{}'.format(s3bktobj['sequencer'])
                else:
                    msg = 'Error, unexpected JSON object and bucket'

            elif eventSource.startswith('aws:dynamodb'):
                flag = DYNDB
                caller = obj['eventID']
                eventSource = obj['eventSource']
                ev = obj['eventName']
                eventOp = ev
                ddbobj = obj['dynamodb']
                mod = ''
                if 'NewImage' in ddbobj:
                    mod += 'New:{}'.format(str(ddbobj['NewImage']))
                if 'OldImage' in ddbobj:
                    mod += ':Old:{}'.format(str(ddbobj['OldImage']))
                msg = mod
                if 'SequenceNumber' in ddbobj:
                    caller += ':{}'.format(ddbobj['SequenceNumber'])
                if 'eventSourceARN' in obj:
                    arn = obj['eventSourceARN']
                    eventSource = arn
                    arns = arn.split(":")
                    acct = arns[4]
                    if accountID == 'unset':
                        accountID = acct
                    elif acct != accountID:
                        accountID +=':{}'.format(acct)
                    reg = arns[3]
                    if region == 'unset':
                        region = reg
                    elif reg != region:              
                        region += ':{}'.format(reg)
            else:
                flag = UNKNOWN
        elif eventSource.startswith('ext:invokeCLI'):
            flag = INVCLI
        elif eventSource.startswith('int:invokeCLI'):
            flag = INVCLI
        elif eventSource.startswith('lib:invokeCLI'):
            flag = INVCLI
        else:
            flag = UNKNOWN

        if flag == INVCLI:
            eventSource = 'aws:CLIInvoke:{}'.format(event['eventSource']);
            #caller set above ('requestId')
            if 'msg' in event:
                msg = event['msg']
            if 'accountId' in event:
                acct = event['accountId']
                if accountID == 'unset':
                    accountID = acct
                elif acct != accountID:
                    accountID +=':{}'.format(acct)
            if 'functionName' in event:
                eventOp = event['functionName']
            #else: leave eventOp unset
            

        if flag == UNKNOWN:
            eventSource = 'unknown_source:{}'.format(functionName)

    if eventSource == 'unset':
        #if functionName is "unset" then context is null!
        eventSource = 'unknown_source:{}'.format(functionName)

    dynamodb = boto3.resource('dynamodb', region_name='ZZZZ')
    table = dynamodb.Table('QQQQ')
    tsint = int(round(time.time() * 1000)) #msecs in UTC
    #since timestamps may be only second resolution, 
    #two events may record at the same ts
    #spotFns is indexed on timestamp and requestID, so distinguish 
    #two events with the same timestamp via postfix on requestID
    requestID += ':{}'.format(prefix)
    table.put_item( Item={
        'ts': tsint,
        'requestID': requestID,
        'thisFnARN': myarn,
        'caller': caller,
        'eventSource': eventSource,
        'eventOp': eventOp,
        'region': region,
        'accountID': accountID,
        'sourceIP': sourceIP,
        'message': msg,
        'duration': int(round(duration)),
        'error': errorstr,
        }
    )

