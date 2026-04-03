import json

with open('workflows/qa_workflow.json', encoding='utf-8') as f:
    wf = json.load(f)

new_js = """\
const PUBLIC_API_BASE_URL = 'https://quadruplication-satisfyingly-corrina.ngrok-free.dev';

const resp = $input.item.json;
const intentData = $('Intent Router').first().json;
const results = (resp && Array.isArray(resp.results)) ? resp.results : [];
const keyword = intentData.keyword || '';

var message;

if (results.length === 0) {
  message = {
    type: 'text',
    text: '\u627e\u4e0d\u5230\u5305\u542b\u300c' + keyword + '\u300d\u7684\u6a94\u6848\u3002\\n\\n\u8acb\u5617\u8a66\u5176\u4ed6\u95dc\u9375\u5b57\uff0c\u6216\u8f38\u5165\u300c\u627e\u6a94\u6848\u300d\u91cd\u8a66\u3002'
  };
} else {
  var fileRows = results.slice(0, 10).map(function(r, i) {
    var url = PUBLIC_API_BASE_URL + r.download_url;
    var displayName = (i + 1) + '. ' + r.file_name;
    return {
      type: 'box',
      layout: 'horizontal',
      spacing: 'sm',
      margin: 'sm',
      contents: [
        {
          type: 'text',
          text: displayName,
          wrap: true,
          flex: 4,
          size: 'sm',
          color: '#1a73e8',
          decoration: 'underline',
          action: {
            type: 'uri',
            label: '\u4e0b\u8f09',
            uri: url
          }
        },
        {
          type: 'button',
          style: 'secondary',
          height: 'sm',
          flex: 2,
          action: {
            type: 'message',
            label: '\u554f',
            text: '\u554f:' + r.file_name
          }
        }
      ]
    };
  });

  var flexContent = {
    type: 'bubble',
    header: {
      type: 'box',
      layout: 'vertical',
      backgroundColor: '#1DB446',
      contents: [
        {
          type: 'text',
          text: '\u627e\u5230 ' + results.length + ' \u500b\u76f8\u95dc\u6a94\u6848',
          color: '#ffffff',
          weight: 'bold',
          size: 'md'
        }
      ]
    },
    body: {
      type: 'box',
      layout: 'vertical',
      spacing: 'none',
      contents: fileRows
    }
  };

  if (results.length > 10) {
    flexContent.footer = {
      type: 'box',
      layout: 'vertical',
      contents: [
        {
          type: 'text',
          text: '\uff08\u5171 ' + results.length + ' \u7b46\uff0c\u986f\u793a\u524d 10 \u7b46\uff09',
          size: 'xs',
          color: '#999999',
          align: 'center'
        }
      ]
    };
  }

  message = {
    type: 'flex',
    altText: '\u627e\u5230 ' + results.length + ' \u500b\u76f8\u95dc\u6a94\u6848',
    contents: flexContent
  };
}

var replyBody = JSON.stringify({
  replyToken: intentData.replyToken,
  messages: [message]
});

return {
  json: {
    lineUserId: intentData.lineUserId,
    replyToken: intentData.replyToken,
    replyText: '\u627e\u5230 ' + results.length + ' \u500b\u76f8\u95dc\u6a94\u6848',
    replyBody: replyBody
  }
};"""

for n in wf['nodes']:
    if n.get('name') == 'Build File Links Reply':
        n['parameters']['jsCode'] = new_js
        print('updated')

with open('workflows/qa_workflow.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, ensure_ascii=False, indent=2)
print('saved')
