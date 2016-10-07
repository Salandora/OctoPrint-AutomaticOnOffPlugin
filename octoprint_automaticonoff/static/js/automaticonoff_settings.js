$(function() {
    function AutomaticOnOffSettingsViewModel(parameters) {
        var self = this;
        
        self.settings = parameters[0];
        self.apiList = ko.observableArray([]);

        self.onSettingsShown = function() {
            self.requestData();
        };

        self.requestData = function() {
            $.ajax({
                url: API_BASEURL + "plugin/automaticonoff",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({command: "list_apis"}),
                contentType: "application/json; charset=UTF-8",
                success: self.fromResponse
            });
        };

        self.fromResponse = function(response) {
            self.apiList(response.apis);
        };
    }

    // view model class, parameters for constructor, container to bind to
    ADDITIONAL_VIEWMODELS.push([
        AutomaticOnOffSettingsViewModel,
        ["settingsViewModel"],
        ["#settings_plugin_automaticonoff"]
    ]);
});
