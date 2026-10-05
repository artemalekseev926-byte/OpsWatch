var params = JSON.parse(value);
var url = params.URL;
delete params.URL;

var request = new HttpRequest();
request.addHeader('Content-Type: application/json');
var response = request.post(url, JSON.stringify(params));

if (request.getStatus() < 200 || request.getStatus() >= 300) {
    throw 'OpsWatch: HTTP ' + request.getStatus() + ' ' + response;
}

return 'OK';
