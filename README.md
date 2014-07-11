About
-----

`umichsched` is a module to get class scheduling information from the [umich
API][umich-api] and to use it to form a class schedule. In particular,
`umichsched` takes into account the fact that classes on different campuses
can't be scheduled consecutively, which other scheduling programs probably
don't know about.

  [umich-api]: http://developer.it.umich.edu/

Requirements
------------

`umichsched` requires Python 3 and the [requests][requests] module.

  [requests]: http://docs.python-requests.org/en/latest/


Usage
-----

You'll need to set up the API, as detailed below, before being able to use the
module.

See the `example.py` file for a fully-functioning example. Just change the
classes, the term, and set/omit the lunch provided and run it.

By default, criteria such as ensuring classes don't conflict and consecutive
classes don't span multiple campuses are applied. To add another custom
criterion, use the `ClassPicker.add_criterion` method to add a predicate. It
should take a schedule -- a list of `umich.Section`s -- as its argument and
return whether or not that schedule is acceptable.

Setting up the API
------------------

`umichsched` needs a umich API key, which you can get from the [API
site][umich-api], with the "Schedule of Classes" and "Buildings" sources.

 1. Go to Applications and make a new application. You only need to fill in the
    "name" field.

 2. Go to APIs and select "Schedule of Classes". (Ignore anything with "SOAP"
    in its name.) Select the application you just made and click the subscribe
button. (The default tier is fine.) Repeat for the "Buildings" API.

 3. Set "Token Validity" to a high number of seconds, so that the key doesn't
    expire while you're trying to use it, and then generate a production key.
Copy that key into the file `access_token` in the project root, with the word
"Bearer" before it, like in`access_token.example`.

License
-------

The MIT License (MIT)

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

